"""Boiler diagnostic sensor for Home Climate Control.

Listens to the HCS device's retained `hcs/<node>/boiler_diag` topic (plain
English text, e.g. "low water pressure" / "no faults") and exposes it as a
`sensor` entity. Raw flags ride along as attributes when the device publishes
them via `boiler_state` + the device's own status API.
"""

from __future__ import annotations

import logging

from homeassistant.components import mqtt
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def _topic_for_node(node_id: str, key: str) -> str:
    """Prefer the entry's node; fall back to wildcard if unknown."""
    node = (node_id or "").strip()
    return f"hcs/{node}/{key}" if node else f"hcs/+/{key}"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the boiler diagnostic sensor from a config entry."""
    node_hint = entry.data.get("node_id", "")
    sensor = BoilerDiagSensor(entry.entry_id, node_hint)
    fs_sensor = FailsafeSensor(entry.entry_id, node_hint)
    hass.data[DOMAIN][entry.entry_id]["boiler_diag_sensor"] = sensor
    hass.data[DOMAIN][entry.entry_id]["failsafe_sensor"] = fs_sensor
    async_add_entities([sensor, fs_sensor])
    # Dynamic custom 1-Wire probes (role=custom on the gateway)
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    backend = data.get("backend") or getattr(data.get("controller"), "backend", None)
    if backend is not None:
        mgr = ProbeManager(hass, entry, backend, async_add_entities)
        data["probe_manager"] = mgr
        mgr.start()


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
            self.hass, _topic_for_node(self._node_hint, "boiler_diag"), on_message, 0
        )

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
            self.hass, _topic_for_node(self._node_hint, "failsafe"), on_message, 0
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._sub:
            self._sub()
            self._sub = None
        await super().async_will_remove_from_hass()


class CustomProbeSensor(SensorEntity):
    """Named custom 1-Wire probe published by an HCS gateway (role=custom)."""

    _attr_should_poll = False
    _attr_device_class = "temperature"
    _attr_native_unit_of_measurement = "°C"
    _attr_state_class = "measurement"
    _attr_icon = "mdi:thermometer"

    def __init__(self, entry_id: str, node_hint: str, name: str, backend) -> None:
        self._entry_id = entry_id
        self._node_hint = node_hint
        self._probe_name = name
        self._backend = backend
        self._attr_name = f"Probe {name.replace('_', ' ').title()}"
        self._attr_unique_id = f"{DOMAIN}_x_{entry_id}_{name}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="Home Climate Control",
            manufacturer="Home Climate Control",
        )
        self._native: float | None = None
        customs = getattr(backend, "custom_sensors", lambda: {})()
        if name in customs:
            self._native = customs[name]

    @property
    def native_value(self):
        return self._native

    @property
    def extra_state_attributes(self):
        return {"probe_name": self._probe_name, "source": "hcs_1wire"}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        @callback
        def _refresh() -> None:
            customs = getattr(self._backend, "custom_sensors", lambda: {})()
            v = customs.get(self._probe_name)
            if v is not None:
                self._native = v
                self.async_write_ha_state()

        add = getattr(self._backend, "add_sensors_listener", None)
        if callable(add):
            add(_refresh)
            self._unsub = lambda: getattr(
                self._backend, "remove_sensors_listener", lambda cb: None
            )(_refresh)
        else:
            self._unsub = None
        # also subscribe live x/<name> topic as a belt-and-braces path
        topic = _topic_for_node(self._node_hint, f"x/{self._probe_name}")

        @callback
        def on_message(msg) -> None:
            try:
                self._native = float((msg.payload or "").strip())
                self.async_write_ha_state()
            except (TypeError, ValueError):
                pass

        self._sub = await mqtt.async_subscribe(self.hass, topic, on_message, 0)

    async def async_will_remove_from_hass(self) -> None:
        if getattr(self, "_unsub", None):
            self._unsub()
        if getattr(self, "_sub", None):
            self._sub()
        await super().async_will_remove_from_hass()


class ProbeManager:
    """Watches the board sensors snapshot and adds custom probe entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        backend,
        async_add_entities: AddEntitiesCallback,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.backend = backend
        self._add = async_add_entities
        self._known: dict[str, CustomProbeSensor] = {}

    def start(self) -> None:
        add = getattr(self.backend, "add_sensors_listener", None)
        if callable(add):
            add(self._on_snapshot)
        # seed from current snapshot
        self._on_snapshot()

    @callback
    def _on_snapshot(self) -> None:
        snap = getattr(self.backend, "sensors_snapshot", lambda: [])()
        customs = getattr(self.backend, "custom_sensors", lambda: {})()
        names = set()
        for d in snap or []:
            if isinstance(d, dict) and d.get("role") == "custom" and d.get("name"):
                names.add(str(d["name"]))
        # also pick up any live custom values even if snapshot lags
        names |= set(customs.keys())
        new = []
        for name in sorted(names):
            if name in self._known:
                continue
            ent = CustomProbeSensor(
                self.entry.entry_id,
                self.entry.data.get("node_id", ""),
                name,
                self.backend,
            )
            self._known[name] = ent
            new.append(ent)
        if new:
            self._add(new)
