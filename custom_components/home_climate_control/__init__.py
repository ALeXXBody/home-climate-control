"""Home Climate Control integration setup."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .const import (
    BACKEND_DEMO,
    BACKEND_HCS,
    CONF_BACKEND,
    CONF_NODE_ID,
    CONF_OUTDOOR_SENSOR,
    CONF_PRESET_OFFSETS,
    CONF_WIND_ENABLED,
    CONF_WIND_ENTITY,
    CONF_WIND_MAX_DELTA,
    CONF_OCCUPANCY_AWAY_PRESET,
    CONF_OCCUPANCY_ENABLED,
    CONF_OCCUPANCY_HOME_PRESET,
    CONF_OCCUPANCY_TRACKERS,
    CONF_SCHEDULE_ENTITY,
    CONF_SCHEDULE_OFF_PRESET,
    CONF_SCHEDULE_ON_PRESET,
    CONF_ZONES,
    PRESET_AWAY,
    PRESET_COMFORT,
    PRESET_ECO,
    DEFAULT_BOILER_MIN_MODULATION,
    DEFAULT_WIND_MAX_DELTA,
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
    from .setback import SetbackLearner
    from .deadtime import DeadTimeEstimator
    from .insulation import InsulationScorer
    from .datalogger import TrainingDataLogger
    from .gasmeter import GasMeter
    from .panel import async_register_panel
    from .websocket_api import async_setup_websocket

    hass.data.setdefault(DOMAIN, {})

    # Ensure the config entry has a stable unique_id so MQTT rediscovery of
    # the same (or any) HCS board is treated as already configured.
    # Guarded: never fight over a unique_id another entry already owns —
    # async_update_entry fires the update listener (reload), and a refused
    # duplicate would loop setup/reload forever.
    node = (entry.data.get(CONF_NODE_ID) or "").strip()
    backend_type = entry.data.get(CONF_BACKEND, BACKEND_HCS)
    if backend_type == BACKEND_HCS and node:
        want_uid = f"hcs_{node}"
        if entry.unique_id != want_uid and not any(
            other.entry_id != entry.entry_id and other.unique_id == want_uid
            for other in hass.config_entries.async_entries(DOMAIN)
        ):
            hass.config_entries.async_update_entry(entry, unique_id=want_uid)

    opts = entry.options
    backend = _build_backend(hass, entry, opts)
    tuner = CurveAutoTuner(
        hass,
        opts.get("curve_coeff", DEFAULT_CURVE_COEFF),
        enabled=opts.get("autotune_curve", True),
    )
    await tuner.async_load()
    setbacks = SetbackLearner(hass, enabled=opts.get("learn_setbacks", True))
    await setbacks.async_load()
    deadtime = DeadTimeEstimator(hass)
    await deadtime.async_load()
    insulation = InsulationScorer(hass)
    await insulation.async_load()
    datalogger = TrainingDataLogger(hass)
    datalogger.async_start()
    gas = GasMeter(
        hass,
        rated_power_kw=opts.get("rated_heat_input_kw", 24.0),
        min_power_kw=opts.get("min_heat_input_kw", 0.0),
        nomod_factor=opts.get("nomod_duty_factor", 0.6),
        calibration=opts.get("gas_calibration", 1.0),
        price_per_kwh=opts.get("gas_price_per_kwh"),
    )
    await gas.async_load()
    controller = CentralController(
        hass,
        backend,
        curve_coeff=tuner.coeff,
        design_outdoor=-10.0,
        min_flow=opts.get("min_flow_temp", DEFAULT_MIN_FLOW_TEMP),
        max_flow=opts.get("max_flow_temp", DEFAULT_MAX_FLOW_TEMP),
        autotune=tuner,
        outdoor_sensor=opts.get(CONF_OUTDOOR_SENSOR)
        or entry.data.get(CONF_OUTDOOR_SENSOR),
        wind_entity=opts.get(CONF_WIND_ENTITY),
        # Explicit toggle with a sensible fallback: when the flag was never
        # stored (older configs), an entity selection implies enabled.
        wind_enabled=opts.get(CONF_WIND_ENABLED, bool(opts.get(CONF_WIND_ENTITY))),
        preset_offsets=opts.get(CONF_PRESET_OFFSETS),
        wind_max_delta=opts.get(CONF_WIND_MAX_DELTA, DEFAULT_WIND_MAX_DELTA),
        min_modulation_pct=opts.get(
            "boiler_min_modulation", DEFAULT_BOILER_MIN_MODULATION
        ),
        duty_cycle_enabled=opts.get("duty_cycle_enabled", True),
    )
    from .schedule import ScheduleFollower

    schedule = ScheduleFollower(
        hass,
        entity_id=opts.get(CONF_SCHEDULE_ENTITY)
        or entry.data.get(CONF_SCHEDULE_ENTITY),
        on_preset=opts.get(CONF_SCHEDULE_ON_PRESET, PRESET_COMFORT),
        off_preset=opts.get(CONF_SCHEDULE_OFF_PRESET, PRESET_ECO),
    )
    from .occupancy import OccupancyFollower

    trackers = opts.get(CONF_OCCUPANCY_TRACKERS) or entry.data.get(
        CONF_OCCUPANCY_TRACKERS
    ) or []
    if isinstance(trackers, str):
        trackers = [trackers]
    occupancy = OccupancyFollower(
        hass,
        entity_ids=list(trackers),
        away_preset=opts.get(CONF_OCCUPANCY_AWAY_PRESET, PRESET_AWAY),
        home_preset=opts.get(CONF_OCCUPANCY_HOME_PRESET, PRESET_COMFORT),
        enabled=bool(opts.get(CONF_OCCUPANCY_ENABLED, False)),
        schedule=schedule,
    )
    controller.setbacks = setbacks
    controller.deadtime = deadtime
    controller.insulation = insulation
    controller.datalogger = datalogger
    controller.gas = gas
    controller.schedule = schedule
    controller.occupancy = occupancy
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
    # Tier 3/4 per-room sensor maps
    lux_map = {z._lux_sensor: z for z in zones if getattr(z, "_lux_sensor", None)}
    co2_map = {z._co2_sensor: z for z in zones if getattr(z, "_co2_sensor", None)}
    valve_map = {
        z._trv_position_entity: z
        for z in zones
        if getattr(z, "_trv_position_entity", None)
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
    watched = (
        list(temp_map.keys()) + list(trv_map.keys()) + window_entities
        + list(lux_map.keys()) + list(co2_map.keys()) + list(valve_map.keys())
    )
    if not watched:
        return

    for entity_id, zone in temp_map.items():
        state = hass.states.get(entity_id)
        if state is not None and state.state not in ("unknown", "unavailable"):
            try:
                zone.on_sensor_update(float(state.state), None)
            except ValueError:
                pass

    def _seed_float(entity_id, zone, handler):
        state = hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return
        try:
            handler(float(state.state))
        except (TypeError, ValueError):
            pass

    for entity_id, zone in lux_map.items():
        _seed_float(entity_id, zone, zone.on_lux_update)
    for entity_id, zone in co2_map.items():
        _seed_float(entity_id, zone, zone.on_co2_update)
    for entity_id, zone in valve_map.items():
        _seed_float(entity_id, zone, zone.on_valve_update)

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

        if entity_id in lux_map:
            try:
                lux_map[entity_id].on_lux_update(float(new.state))
            except (TypeError, ValueError):
                pass
            return
        if entity_id in co2_map:
            try:
                co2_map[entity_id].on_co2_update(float(new.state))
            except (TypeError, ValueError):
                pass
            return
        if entity_id in valve_map:
            try:
                valve_map[entity_id].on_valve_update(float(new.state))
            except (TypeError, ValueError):
                pass
            return

        if entity_id in trv_map:
            for zone in trv_map[entity_id]:
                if hasattr(zone, "on_trv_update"):
                    zone.on_trv_update()
            return

        if entity_id in window_entities:
            # Aggregate: any open sensor keeps the room paused.
            for z in zones:
                if entity_id not in z.window_sensor_entities:
                    continue
                any_open = False
                for sid in z.window_sensor_entities:
                    st = hass.states.get(sid)
                    if st is not None and st.state == "on":
                        any_open = True
                        break
                z.on_sensor_update(None, any_open)

    entry.async_on_unload(async_track_state_change_event(hass, watched, _on_state))


def get_controller(hass: HomeAssistant, entry: ConfigEntry) -> CentralController:
    return hass.data[DOMAIN][entry.entry_id]["controller"]


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:

    # Audit F1: sensor platform was never unloaded, boiler_info kept its
    # MQTT subscription and update_checker its interval after entry removal.
    stored = hass.data[DOMAIN].pop(entry.entry_id, None)
    unload_ok = True
    if stored is not None:
        controller = stored["controller"]
        await controller.async_stop()
        # Final training-log flush so buffered rows survive the unload.
        dl = getattr(controller, "datalogger", None)
        if dl is not None:
            await dl.async_stop()

        bi = stored.get("boiler_info")
        if bi is not None:
            await bi.async_unload()
            from .boiler_info import _ACTIVE as _bi_active

            _bi_active.pop(entry.entry_id, None)

        unload_ok = await hass.config_entries.async_unload_platforms(
            entry, ["climate", "sensor", "update"]
        )

    remaining = [
        k
        for k, v in hass.data.get(DOMAIN, {}).items()
        if isinstance(v, dict) and "controller" in v
    ]
    if not remaining:
        # NOTE: deliberately NOT unregistering the sidebar panel here.
        # Unregistering kicks HA off the /home-climate route (it falls back
        # to the default dashboard), and every options save reloads this
        # entry — one switch flip used to throw the user to Overview.
        # The panel renders an empty state gracefully with no entry.

        from .update_checker import get_update_checker

        uc = get_update_checker(hass)
        if uc is not None:
            await uc.async_stop()
            import custom_components.home_climate_control.update_checker as _uc_mod

            _uc_mod._ACTIVE = None

        from .firmware_manager import get_firmware_manager

        mgr = get_firmware_manager(hass)
        if mgr is not None and hasattr(mgr, "async_stop"):
            await mgr.async_stop()
            hass.data.get(DOMAIN, {}).pop("firmware_manager", None)

    return unload_ok
