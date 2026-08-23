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
from .update_checker import version_tuple

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    async_add_entities([HcsFirmwareUpdateEntity(hass, entry.entry_id)])


class HcsFirmwareUpdateEntity(UpdateEntity):
    # Polling re-diffed devices every cycle and flipped available/installed
    # versions during OTA, which spammed HA "state" toasts. Discovery + the
    # 6 h checker own freshness; this entity only reads cached checker info.
    _attr_should_poll = False
    _attr_title = "Home Climate System firmware"
    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_icon = "mdi:chip"
    _attr_supported_features = (
        UpdateEntityFeature.INSTALL | UpdateEntityFeature.RELEASE_NOTES
    )

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self.hass = hass
        self._entry_id = entry_id
        self._attr_unique_id = f"{DOMAIN}_fw_{entry_id}"
        self._in_progress = False
        self._attr_entity_picture = self._brand_icon_url()

    def _brand_icon_url(self) -> str | None:
        """Absolute URL of the bundled brand icon for the Updates card."""
        from pathlib import Path

        if not (Path(__file__).parent / "brand" / "icon.png").is_file():
            return None
        try:
            from homeassistant.helpers.network import get_url

            base = get_url(self.hass, allow_cloud=False, prefer_internal=True)
            return (
                f"{base}/home_climate_control_static/"
                f"brand/icon.png"
            )
        except Exception:  # noqa: BLE001
            return None

    @property
    def installed_version(self) -> str | None:
        """Lowest reported version across known devices (stable, no flap)."""
        mgr = self._mgr()
        devs = list(getattr(mgr, "devices", {}).values()) if mgr else []
        versions = [d.version for d in devs if getattr(d, "version", None)]
        if not versions:
            return None
        return sorted(versions, key=version_tuple)[0]

    @property
    def latest_version(self) -> str | None:
        info = self._checker_info()
        if info.get("installing"):
            # During OTA cooldown report installed==latest so HA stops toasting
            # "update available" while boards still announce the old build.
            return self.installed_version
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
            "installing": bool(info.get("installing")),
        }

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

        outdated = list(uc.info.get("outdated_devices") or [])
        if not outdated:
            # One forced re-diff in case the entity was opened stale.
            latest = uc.info.get("latest_version")
            if latest:
                outdated = uc._outdated_devices(latest)
            if not outdated:
                return

        uc.mark_install_started()
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
                await asyncio.sleep(35)
        finally:
            self._in_progress = False
            # Dismiss the one-shot notification for this tag; keep _notified_tag
            # so discovery during reboot cannot recreate it.
            from homeassistant.components import persistent_notification

            tag = uc.info.get("latest_tag")
            if tag:
                persistent_notification.async_dismiss(
                    self.hass, f"{DOMAIN}_fw_{tag}"
                )
            self.async_write_ha_state()

    async def async_release_notes(self) -> str | None:
        return self._checker_info().get("changelog")
