"""Home Climate Control integration setup."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .const import (
    BACKEND_DEMO,
    BACKEND_HCS,
    CONF_BACKEND,
    CONF_NODE_ID,
    CONF_ZONES,
    DEFAULT_CURVE_COEFF,
    DEFAULT_MAX_FLOW_TEMP,
    DEFAULT_MIN_FLOW_TEMP,
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
    from .boiler.demo import DemoBoilerBackend
    from .boiler.hcs_mqtt import HcsMqttBackend

    backend_type = entry.data.get(CONF_BACKEND, BACKEND_HCS)
    min_flow = opts.get("min_flow_temp", DEFAULT_MIN_FLOW_TEMP)
    max_flow = opts.get("max_flow_temp", DEFAULT_MAX_FLOW_TEMP)

    if backend_type == BACKEND_HCS:
        return HcsMqttBackend(
            hass,
            node_id=entry.data.get(CONF_NODE_ID, ""),
            min_flow=min_flow,
            max_flow=max_flow,
        )

    if backend_type == BACKEND_DEMO:
        rooms: dict[str, float] = {}
        for z in opts.get(CONF_ZONES, []):
            name = z.get("name")
            if name:
                rooms[name] = float(z.get("demo_start_temp", 18.0))
        return DemoBoilerBackend(
            min_flow,
            max_flow,
            outdoor=float(entry.data.get("demo_outdoor", DEMO_DEFAULT_OUTDOOR)),
            rooms=rooms,
        )

    raise ValueError(f"Unknown backend type: {backend_type!r}")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from .autotune import CurveAutoTuner
    from .central import CentralController
    from .panel import async_register_panel
    from .websocket_api import async_setup_websocket

    hass.data.setdefault(DOMAIN, {})

    opts = entry.options
    backend = _build_backend(hass, entry, opts)
    tuner = CurveAutoTuner(
        hass,
        opts.get("curve_coeff", DEFAULT_CURVE_COEFF),
        enabled=opts.get("autotune_curve", True),
    )
    await tuner.async_load()
    controller = CentralController(
        hass,
        backend,
        curve_coeff=tuner.coeff,
        design_outdoor=-10.0,
        min_flow=opts.get("min_flow_temp", DEFAULT_MIN_FLOW_TEMP),
        max_flow=opts.get("max_flow_temp", DEFAULT_MAX_FLOW_TEMP),
        autotune=tuner,
    )
    hass.data[DOMAIN][entry.entry_id] = {
        "controller": controller,
        "zones_cfg": opts.get(CONF_ZONES, []),
        "backend": backend,
        "backend_type": entry.data.get(CONF_BACKEND, BACKEND_HCS),
        "node_id": entry.data.get(CONF_NODE_ID, ""),
    }

    async_setup_websocket(hass)
    await async_register_panel(hass)

    from .firmware_manager import async_setup_firmware_manager
    from .boiler_info import async_setup_boiler_info
    from .update_checker import async_setup_update_checker

    await async_setup_firmware_manager(hass)
    await async_setup_update_checker(hass)
    hass.data[DOMAIN][entry.entry_id]["boiler_info"] = (
        await async_setup_boiler_info(hass, entry.entry_id)
    )

    await hass.config_entries.async_forward_entry_setups(
        entry, ["climate", "sensor", "update"]
    )
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def wire_zone_sensors(hass: HomeAssistant, entry: ConfigEntry, zones: list) -> None:
    """Subscribe external temp sensors, TRV climates, and window sensors.

    Room temperature source priority:
      1. External temperature sensor (if configured)
      2. TRV climate entity current_temperature (fallback)
    HCS/ESP is never a room sensor — it is the boiler gateway only.
    """
    from homeassistant.core import callback
    from homeassistant.helpers.event import async_track_state_change_event

    temp_map = {
        z.temp_sensor_entity: z
        for z in zones
        if z.temp_sensor_entity
    }
    trv_map: dict[str, list] = {}
    for z in zones:
        for trv in getattr(z, "trv_entities", None) or []:
            trv_map.setdefault(trv, []).append(z)
        # single-TRV property
        trv = getattr(z, "trv_entity", None)
        if trv:
            trv_map.setdefault(trv, [])
            if z not in trv_map[trv]:
                trv_map[trv].append(z)

    window_entities = sorted({s for z in zones for s in z.window_sensor_entities})
    watched = list(temp_map.keys()) + list(trv_map.keys()) + window_entities
    if not watched:
        return

    for entity_id, zone in temp_map.items():
        state = hass.states.get(entity_id)
        if state is not None and state.state not in ("unknown", "unavailable"):
            try:
                zone.on_sensor_update(float(state.state), None)
            except ValueError:
                pass

    for entity_id, room_list in trv_map.items():
        for zone in room_list:
            if not zone.temp_sensor_entity and hasattr(zone, "on_trv_update"):
                zone.on_trv_update()

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

        if entity_id in trv_map:
            for zone in trv_map[entity_id]:
                if hasattr(zone, "on_trv_update"):
                    zone.on_trv_update()
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

    # Audit F1: sensor platform was never unloaded, boiler_info kept its
    # MQTT subscription and update_checker its interval after entry removal.
    stored = hass.data[DOMAIN].pop(entry.entry_id, None)
    unload_ok = True
    if stored is not None:
        controller = stored["controller"]
        await controller.async_stop()

        bi = stored.get("boiler_info")
        if bi is not None:
            await bi.async_unload()

        unload_ok = await hass.config_entries.async_unload_platforms(
            entry, ["climate", "sensor", "update"]
        )

    remaining = [
        k
        for k, v in hass.data.get(DOMAIN, {}).items()
        if isinstance(v, dict) and "controller" in v
    ]
    if not remaining:
        await async_unregister_panel(hass)

        from .update_checker import get_update_checker

        uc = get_update_checker(hass)
        if uc is not None:
            await uc.async_stop()
            import custom_components.home_climate_control.update_checker as _uc_mod

            _uc_mod._ACTIVE = None

    return unload_ok
