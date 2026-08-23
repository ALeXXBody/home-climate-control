"""Boiler diagnostic sensor for Home Climate Control.

Listens to the HCS device's retained `hcs/<node>/boiler_diag` topic (plain
English text, e.g. "low water pressure" / "no faults") and exposes it as a
`sensor` entity. Raw flags ride along as attributes when the device publishes
them via `boiler_state` + the device's own status API.
"""

from __future__ import annotations

import logging

from homeassistant.components import mqtt
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the boiler diagnostic sensor from a config entry."""
    node_hint = entry.data.get("otgw_node", "")
    sensor = BoilerDiagSensor(entry.entry_id, node_hint)
    fs_sensor = FailsafeSensor(entry.entry_id, node_hint)
    hass.data[DOMAIN][entry.entry_id]["boiler_diag_sensor"] = sensor
    hass.data[DOMAIN][entry.entry_id]["failsafe_sensor"] = fs_sensor
    async_add_entities([sensor, fs_sensor])


class BoilerDiagSensor(SensorEntity):
    """Human-readable boiler fault summary published by an HCS device."""

    _attr_should_poll = False
    _attr_name = "Boiler diagnostic"
    _attr_icon = "mdi:fire-alert"
    _attr_device_class = None  # plain text state
    native_value = "unknown"

    def __init__(self, entry_id: str, node_hint: str) -> None:
        self._entry_id = entry_id
        self._node_hint = node_hint
        self._sub = None
        self._attr_unique_id = f"{DOMAIN}_boiler_diag_{entry_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="Home Climate Control",
            manufacturer="Home Climate Control",
        )

    @property
    def extra_state_attributes(self):
        return {"raw_asf": self._raw_asf, "raw_oem": self._raw_oem}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        @callback
        def on_message(msg) -> None:
            text = (msg.payload or "").strip()
            if not text:
                return
            # derive raw values from the text where possible
            self._raw_asf = None
            self._raw_oem = None
            if "diagnostic code " in text:
                try:
                    self._raw_oem = int(text.rsplit(" ", 1)[1])
                except (ValueError, IndexError):
                    pass
            self.native_value = text
            self.async_write_ha_state()

        self._sub = await mqtt.async_subscribe(
            self.hass, "hcs/+/boiler_diag", on_message, 0
        )

        # seed from any retained message already in local state cache
        state = self.hass.states.get(self.entity_id)
        if state is None:
            self.native_value = "unknown"

    async def async_will_remove_from_hass(self) -> None:
        if self._sub:
            self._sub()
            self._sub = None
        await super().async_will_remove_from_hass()

    _raw_asf = None
    _raw_oem = None


class FailsafeSensor(SensorEntity):
    """Connection-loss failsafe state reported by an HCS device.

    State: OFF (normal), HOLD (link lost, inside grace) or ON (failsafe
    heating active). Retained on the device so it survives reboots.
    """

    _attr_should_poll = False
    _attr_name = "Heating failsafe"
    _attr_icon = "mdi:shield-home-outline"
    native_value = "OFF"

    def __init__(self, entry_id: str, node_hint: str) -> None:
        self._entry_id = entry_id
        self._node_hint = node_hint
        self._sub = None
        self._attr_unique_id = f"{DOMAIN}_failsafe_{entry_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="Home Climate Control",
            manufacturer="Home Climate Control",
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        @callback
        def on_message(msg) -> None:
            v = (msg.payload or "").strip().upper()
            if v in ("ON", "HOLD", "OFF"):
                self.native_value = v
                self.async_write_ha_state()

        self._sub = await mqtt.async_subscribe(
            self.hass, "hcs/+/failsafe", on_message, 0
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._sub:
            self._sub()
            self._sub = None
        await super().async_will_remove_from_hass()
