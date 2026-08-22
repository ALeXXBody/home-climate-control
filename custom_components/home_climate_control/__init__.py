"""Home Climate Control integration setup."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .const import (
    CONF_OTGW_NODE_ID,
    CONF_OTGW_PREFIX,
    CONF_ZONES,
    DEFAULT_CURVE_COEFF,
    DEFAULT_MAX_FLOW_TEMP,
    DEFAULT_MIN_FLOW_TEMP,
    DEFAULT_OTGW_PREFIX,
    DOMAIN,
)

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .central import CentralController

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up when HA loads the integration (YAML or discovery)."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from .boiler.otgw_mqtt import OtgwMqttBackend
    from .central import CentralController
    from .panel import async_register_panel
    from .websocket_api import async_setup_websocket

    hass.data.setdefault(DOMAIN, {})

    opts = entry.options
    backend = OtgwMqttBackend(
        hass,
        prefix=entry.data.get(CONF_OTGW_PREFIX, DEFAULT_OTGW_PREFIX),
        node_id=entry.data.get(CONF_OTGW_NODE_ID, ""),
        min_flow=opts.get("min_flow_temp", DEFAULT_MIN_FLOW_TEMP),
        max_flow=opts.get("max_flow_temp", DEFAULT_MAX_FLOW_TEMP),
    )
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
    }

    async_setup_websocket(hass)
    await async_register_panel(hass)

    await hass.config_entries.async_forward_entry_setups(entry, ["climate"])
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def wire_zone_sensors(hass: HomeAssistant, entry: ConfigEntry, zones: list) -> None:
    """Subscribe room temp + window sensors feeding each zone."""
    from homeassistant.core import callback
    from homeassistant.helpers.event import async_track_state_change_event

    temp_map = {z.temp_sensor_entity: z for z in zones if z.temp_sensor_entity}
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

    # Drop sidebar when no config entries remain.
    remaining = [
        k
        for k, v in hass.data.get(DOMAIN, {}).items()
        if isinstance(v, dict) and "controller" in v
    ]
    if not remaining:
        await async_unregister_panel(hass)

    return unload_ok
