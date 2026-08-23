"""Firmware update entity — the HA-native way to announce & install updates.

One entity per config entry ("Home Climate System firmware"). Shows in
Settings → Updates alongside HACS/HA updates, with the integration's brand
icon, changelog dialog, and an Install button that flashes all outdated
devices over MQTT+HTTP OTA.
"""

from __future__ import annotations

import asyncio
import logging

from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    async_add_entities([HcsFirmwareUpdateEntity(hass, entry.entry_id)])


class HcsFirmwareUpdateEntity(UpdateEntity):
    _attr_should_poll = True          # polls checker + devices every 30 s
    _attr_title = "Home Climate System firmware"
    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_icon = "mdi:chip"
    _attr_supported_features = (
        UpdateEntityFeature.INSTALL
        | UpdateEntityFeature.RELEASE_NOTES
        | UpdateEntityFeature.PROGRESS
    )

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self.hass = hass
        self._entry_id = entry_id
        self._attr_unique_id = f"{DOMAIN}_fw_{entry_id}"
        self._in_progress = False

    @property
    def installed_version(self) -> str | None:
        mgr = self._mgr()
        devs = list(getattr(mgr, "devices", {}).values()) if mgr else []
        online = [d for d in devs if d.online and d.version]
        if online:
            return online[0].version
        return devs[0].version if devs else None

    @property
    def latest_version(self) -> str | None:
        info = self._checker_info()
        return info.get("latest_version") or self.installed_version

    def _mgr(self):
        from .firmware_manager import get_firmware_manager

        return get_firmware_manager(self.hass)

    def _checker_info(self) -> dict:
        from .update_checker import get_update_checker

        uc = get_update_checker(self.hass)
        return uc.info if uc else {}

    @property
    def release_url(self) -> str | None:
        return self._checker_info().get("url")

    @property
    def release_summary(self) -> str | None:
        body = self._checker_info().get("changelog") or ""
        return body[:255] or None

    @property
    def extra_state_attributes(self):
        info = self._checker_info()
        return {
            "outdated_devices": [
                d["node_id"] for d in info.get("outdated_devices", [])
            ],
            "latest_tag": info.get("latest_tag"),
            "changelog": info.get("changelog"),
        }

    async def async_update(self) -> None:
        """Refresh checker data (cheap; GitHub hit is rate-limited inside)."""
        uc = self._checker()
        if uc is not None and not uc.info.get("available"):
            # only re-hit GitHub occasionally when we think we're current;
            # the 6 h job owns that cadence, so just refresh device diff here
            latest = uc.info.get("latest_version")
            if latest:
                uc.info["outdated_devices"] = uc._outdated_devices(latest)
                uc.info["available"] = bool(uc.info["outdated_devices"])

    def _checker(self):
        from .update_checker import get_update_checker

        return get_update_checker(self.hass)

    @property
    def in_progress(self) -> bool:
        return self._in_progress

    async def async_install(
        self, previous_version: str | None = None, options: dict | None = None
    ) -> None:
        """Flash every outdated device with its matching board image."""
        mgr = self._mgr()
        uc = self._checker()
        if not mgr or not uc:
            return

        catalog = {}
        from .firmware_manager import DEFAULT_CATALOG

        for item in DEFAULT_CATALOG:
            catalog[item["board"]] = item

        outdated = uc.info.get("outdated_devices", [])
        if not outdated:
            return

        self._in_progress = True
        self.async_write_ha_state()
        try:
            for dev in outdated:
                node = dev["node_id"]
                item = catalog.get(dev["board"])
                if not item:
                    continue
                try:
                    await mgr.async_trigger_ota(node, item["url"])
                except Exception as err:  # noqa: BLE001
                    _LOGGER.error("OTA to %s failed: %s", node, err)
                await asyncio.sleep(35)  # flash + reboot + re-announce
        finally:
            self._in_progress = False
            self.async_write_ha_state()
            # clear the persistent notification once the flash batch is sent
            from homeassistant.components import persistent_notification

            tag = uc.info.get("latest_tag")
            if tag:
                persistent_notification.async_dismiss(
                    self.hass, f"{DOMAIN}_fw_{tag}"
                )
            uc.info["available"] = False
            uc.info["outdated_devices"] = []

    @property
    def release_notes(self) -> str | None:
        return self._checker_info().get("changelog")
