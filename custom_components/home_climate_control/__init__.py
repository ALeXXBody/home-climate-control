"""Home Climate Control integration setup."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .const import (
    BACKEND_DEMO,
    BACKEND_OTGW_MQTT,
    CONF_BACKEND,
    CONF_OTGW_NODE_ID,
    CONF_OTGW_PREFIX,
    CONF_ZONES,
    DEFAULT_CURVE_COEFF,
    DEFAULT_MAX_FLOW_TEMP,
    DEFAULT_MIN_FLOW_TEMP,
    DEFAULT_OTGW_PREFIX,
    DEMO_DEFAULT_OUTDOOR,
    DOMAIN,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .central import CentralController

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    hass.data.setdefault(DOMAIN, {})
    return True


def _build_backend(hass: HomeAssistant, entry: ConfigEntry, opts: dict):
    from .boiler.demo import DemoOtgwBackend
    from .boiler.otgw_mqtt import OtgwMqttBackend

    backend_type = entry.data.get(CONF_BACKEND, BACKEND_OTGW_MQTT)
    min_flow = opts.get("min_flow_temp", DEFAULT_MIN_FLOW_TEMP)
    max_flow = opts.get("max_flow_temp", DEFAULT_MAX_FLOW_TEMP)

    if backend_type == BACKEND_DEMO:
        rooms: dict[str, float] = {}
        for z in opts.get(CONF_ZONES, []):
            name = z.get("name")
            if name:
                rooms[name] = float(z.get("demo_start_temp", 18.0))
        return DemoOtgwBackend(
            min_flow,
            max_flow,
            outdoor=float(entry.data.get("demo_outdoor", DEMO_DEFAULT_OUTDOOR)),
            rooms=rooms,
        )

    return OtgwMqttBackend(
        hass,
        prefix=entry.data.get(CONF_OTGW_PREFIX, DEFAULT_OTGW_PREFIX),
        node_id=entry.data.get(CONF_OTGW_NODE_ID, ""),
        min_flow=min_flow,
        max_flow=max_flow,
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from .central import CentralController
    from .panel import async_register_panel
    from .websocket_api import async_setup_websocket

    hass.data.setdefault(DOMAIN, {})

    opts = entry.options
    backend = _build_backend(hass, entry, opts)
    controller = CentralController(
        hass,
        backend,
        curve_coeff=opts.get("curve_coeff", DEFAULT_CURVE_COEFF),
        design_outdoor=-10.0,
        min_flow=opts.get("min_flow_temp", DEFAULT_MIN_FLOW_TEMP),
        max_flow=opts.get("max_flow_temp", DEFAULT_MAX_FLOW_TEMP),
    )
    hass.data[DOMAIN][entry.entry_id] = {
        "controller": controller,
        "zones_cfg": opts.get(CONF_ZONES, []),
        "backend": entry.data.get(CONF_BACKEND, BACKEND_OTGW_MQTT),
    }

    async_setup_websocket(hass)
    await async_register_panel(hass)

    from .firmware_manager import async_setup_firmware_manager
    from .boiler_info import async_setup_boiler_info

    await async_setup_firmware_manager(hass)
    hass.data[DOMAIN][entry.entry_id]["boiler_info"] = (
        await async_setup_boiler_info(hass, entry.entry_id)
    )

    await hass.config_entries.async_forward_entry_setups(entry, ["climate", "sensor"])
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def wire_zone_sensors(hass: HomeAssistant, entry: ConfigEntry, zones: list) -> None:
    """Subscribe room temp + window sensors feeding each zone."""
    from homeassistant.core import callback
    from homeassistant.helpers.event import async_track_state_change_event

    temp_map = {
        z.temp_sensor_entity: z
        for z in zones
        if z.temp_sensor_entity
    }
    window_entities = sorted({s for z in zones for s in z.window_sensor_entities})
    watched = list(temp_map.keys()) + window_entities
    if not watched:
        return

    for entity_id, zone in temp_map.items():
        state = hass.states.get(entity_id)
        if state is not None and state.state not in ("unknown", "unavailable"):
            try:
                zone.on_sensor_update(float(state.state), None)
            except ValueError:
                pass
    for entity_id in window_entities:
        state = hass.states.get(entity_id)
        if state is not None:
            open_ = state.state == "on"
            for z in zones:
                if entity_id in z.window_sensor_entities:
                    z.on_sensor_update(None, open_)

    @callback
    def _on_state(event) -> None:
        new = event.data.get("new_state")
        if new is None or new.state in ("unknown", "unavailable"):
            return
        entity_id = event.data["entity_id"]

        zone = temp_map.get(entity_id)
        if zone is not None:
            try:
                zone.on_sensor_update(float(new.state), None)
            except ValueError:
                pass
            return

        if entity_id in window_entities:
            window_open = new.state == "on"
            for z in zones:
                if entity_id in z.window_sensor_entities:
                    z.on_sensor_update(None, window_open)

    entry.async_on_unload(async_track_state_change_event(hass, watched, _on_state))


def get_controller(hass: HomeAssistant, entry: ConfigEntry) -> CentralController:
    return hass.data[DOMAIN][entry.entry_id]["controller"]


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from .panel import async_unregister_panel

    stored = hass.data[DOMAIN].pop(entry.entry_id, None)
    unload_ok = True
    if stored is not None:
        controller = stored["controller"]
        await controller.async_stop()
        unload_ok = await hass.config_entries.async_unload_platforms(entry, ["climate"])

    remaining = [
        k
        for k, v in hass.data.get(DOMAIN, {}).items()
        if isinstance(v, dict) and "controller" in v
    ]
    if not remaining:
        await async_unregister_panel(hass)

    return unload_ok
