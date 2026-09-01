"""WebSocket API for the Home Climate sidebar app."""

from __future__ import annotations

import json
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import (
    CONF_OCCUPANCY_AWAY_PRESET,
    CONF_OCCUPANCY_ENABLED,
    CONF_OCCUPANCY_HOME_PRESET,
    CONF_OCCUPANCY_TRACKERS,
    CONF_OUTDOOR_SENSOR,
    CONF_SCHEDULE_ENTITY,
    CONF_SCHEDULE_OFF_PRESET,
    CONF_SCHEDULE_ON_PRESET,
    CONF_WIND_ENABLED,
    CONF_WIND_ENTITY,
    CONF_WIND_MAX_DELTA,
    CONF_ZONE_CO2_SENSOR,
    CONF_ZONE_FLOOR,
    CONF_ZONE_HEAT_CONTROL,
    CONF_ZONE_LUX_SENSOR,
    CONF_ZONE_RADIATOR_KW,
    CONF_ZONE_TRV_POSITION,
    CONF_ZONE_NAME,
    CONF_ZONE_TEMP_SENSOR,
    CONF_ZONE_TRV_CLIMATES,
    CONF_ZONE_WINDOW_SENSORS,
    CONF_ZONES,
    DEFAULT_BOILER_MIN_MODULATION,
    DEFAULT_CURVE_COEFF,
    DEFAULT_MAX_FLOW_TEMP,
    DEFAULT_MIN_FLOW_TEMP,
    DEFAULT_WIND_MAX_DELTA,
    DEFAULT_ZONE_SETPOINT,
    DOMAIN,
    HEAT_CONTROL_SMART,
    PRESET_AWAY,
    PRESET_COMFORT,
    PRESET_ECO,
    ZONE_PRESETS,
)
from .firmware_manager import (
    async_setup_firmware_manager,
    catalog_item,
    get_firmware_manager,
)

_LOGGER = logging.getLogger(__name__)

INTEGRATION_VERSION = "1.7.0"


def _integration_version() -> str:
    """Return the integration version without blocking filesystem I/O."""
    return INTEGRATION_VERSION


@callback
def async_setup_websocket(hass: HomeAssistant) -> None:
    """Register WebSocket commands (once)."""
    key = f"{DOMAIN}_ws_registered"
    if hass.data.get(key):
        return
    websocket_api.async_register_command(hass, ws_get_status)
    websocket_api.async_register_command(hass, ws_set_zone)
    websocket_api.async_register_command(hass, ws_set_options)
    websocket_api.async_register_command(hass, ws_calibrate_zone)
    websocket_api.async_register_command(hass, ws_add_zone)
    websocket_api.async_register_command(hass, ws_rename_zone)
    websocket_api.async_register_command(hass, ws_remove_zone)
    websocket_api.async_register_command(hass, ws_set_failsafe)
    websocket_api.async_register_command(hass, ws_get_boiler_catalog)
    websocket_api.async_register_command(hass, ws_set_boiler_info)
    websocket_api.async_register_command(hass, ws_check_updates)
    websocket_api.async_register_command(hass, ws_set_github_token)
    websocket_api.async_register_command(hass, ws_list_devices)
    websocket_api.async_register_command(hass, ws_forget_device)
    websocket_api.async_register_command(hass, ws_ping_devices)
    websocket_api.async_register_command(hass, ws_flash_device)
    websocket_api.async_register_command(hass, ws_set_device_settings)
    websocket_api.async_register_command(hass, ws_device_control)
    websocket_api.async_register_command(hass, ws_reboot_device)
    websocket_api.async_register_command(hass, ws_firmware_catalog)
    websocket_api.async_register_command(hass, ws_get_ot_log)
    hass.data[key] = True


def _collect_status(hass: HomeAssistant) -> dict[str, Any]:
    store = hass.data.get(DOMAIN, {})
    boiler_info = None
    try:
        from .boiler_info import get_boiler_info

        bi = get_boiler_info(hass)
        if bi is not None:
            boiler_info = bi.as_dict()
    except Exception:  # noqa: BLE001
        boiler_info = None
    update_info = None
    try:
        from .update_checker import get_update_checker

        uc = get_update_checker(hass)
        if uc is not None:
            update_info = uc.info
    except Exception:  # noqa: BLE001
        update_info = None
    systems: list[dict[str, Any]] = []

    for entry_id, data in store.items():
        if not isinstance(data, dict) or "controller" not in data:
            continue
        controller = data["controller"]
        zones_out: list[dict[str, Any]] = []
        for zone in getattr(controller, "zones", []):
            entity_id = getattr(zone, "entity_id", None)
            state = hass.states.get(entity_id) if entity_id else None
            zones_out.append(
                {
                    "entity_id": entity_id,
                    "name": getattr(zone, "name", None)
                    or (state.name if state else "Zone"),
                    "current_temperature": getattr(zone, "current_temperature", None),
                    "target_temperature": getattr(zone, "target_temperature", None),
                    "hvac_mode": str(getattr(zone, "hvac_mode", "off")),
                    "hvac_action": str(getattr(zone, "hvac_action", "off")),
                    "preset_mode": getattr(zone, "preset_mode", "none"),
                    "demand_level": getattr(zone, "demand_level", lambda: 0)(),
                    "window_open": getattr(zone, "paused", lambda: False)(),
                    "floor": getattr(zone, "floor", 0),
                    "heat_control": getattr(zone, "heater_control", "smart"),
                    "window_sensors": list(
                        getattr(zone, "window_sensor_entities", []) or []
                    ),
                    "trv": getattr(zone, "trv_entity", None),
                    "temp_sensor": getattr(zone, "temp_sensor_entity", None),
                    "temp_source": (
                        (getattr(zone, "extra_state_attributes", {}) or {}).get(
                            "temp_source"
                        )
                        if hasattr(zone, "extra_state_attributes")
                        else None
                    ),
                    "effective_setpoint": getattr(
                        zone, "effective_setpoint", lambda: None
                    )(),
                    "preheat": bool(getattr(zone, "_preheat_active", False)),
                    "lead_time_s": (
                        getattr(zone, "lead_time_s", lambda **k: None)(
                            to_comfort=getattr(zone, "preset_mode", "none")
                            in ("away", "eco")
                        )
                        if hasattr(zone, "lead_time_s")
                        else None
                    ),
                    "dead_time_s": (
                        getattr(zone, "_dead_time_s", lambda: None)()
                        if hasattr(zone, "_dead_time_s")
                        else None
                    ),
                    "state": state.state if state else None,
                    # Tier 3/4
                    "solar_gain": getattr(zone, "solar", None) is not None
                    and zone.solar.active,
                    "co2_ppm": (
                        round(zone.co2.ppm)
                        if getattr(zone, "co2", None) is not None
                        and zone.co2.ppm is not None
                        else None
                    ),
                    "needs_ventilation": (
                        zone.co2.needs_ventilation
                        if getattr(zone, "co2", None) is not None
                        else False
                    ),
                    "valve_pct": getattr(zone, "_valve_pct", None),
                    "balance": (
                        zone.balance.report()
                        if getattr(zone, "balance", None) is not None
                        else None
                    ),
                    "radiator_kw": getattr(zone, "radiator_kw", None),
                    "radiator_kw_est": getattr(zone, "_radiator_kw_est", None),
                }
            )

        diag = {}
        if hasattr(controller, "diagnostics"):
            try:
                diag = controller.diagnostics()
            except Exception:  # noqa: BLE001
                _LOGGER.debug("diagnostics failed", exc_info=True)

        systems.append(
            {
                "entry_id": entry_id,
                "demo": bool(diag.get("demo")),
                "backend": diag.get("backend")
                or data.get("backend_type")
                or getattr(data.get("backend"), "__class__", type("", (), {})).__name__,
                "flow_setpoint": getattr(controller, "flow_setpoint", None),
                "total_demand": getattr(controller, "total_demand", 0),
                "active_zones": list(getattr(controller, "active_zone_names", [])),
                "outdoor_temp": controller.outdoor_temp()
                if hasattr(controller, "outdoor_temp")
                else None,
                "curve_coeff": getattr(controller, "curve_coeff", None),
                "min_flow": getattr(controller, "min_flow", None),
                "max_flow": getattr(controller, "max_flow", None),
                "boiler": diag,
                # Flatten common diag blocks the panel reads as sys.*
                "gas": diag.get("gas"),
                "setbacks": diag.get("setbacks"),
                "autotune": diag.get("autotune"),
                "schedule": diag.get("schedule"),
                "occupancy": diag.get("occupancy"),
                "wind_trim": diag.get("wind_trim"),
                "cycle_guard": diag.get("cycle_guard"),
                "boiler_info": boiler_info,
                "options": _options_view(
                    getattr(
                        hass.config_entries.async_get_entry(entry_id), "options", {}
                    )
                    or {}
                ),
                "update_info": update_info,
                "zones": zones_out,
            }
        )

    mgr = get_firmware_manager(hass)
    devices = mgr.list_devices() if mgr else []

    return {
        "domain": DOMAIN,
        "version": _integration_version(),
        "systems": systems,
        "devices": devices,
        "firmware_catalog": mgr.catalog if mgr else [],
        "support_url": "https://buymeacoffee.com/alexxbody",
        "docs": {
            "software": "https://github.com/ALeXXBody/home-climate-control",
            "hardware": "https://github.com/ALeXXBody/home-climate-system",
            "flash": "https://github.com/ALeXXBody/home-climate-system/blob/main/docs/flash.md",
        },
    }


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/get_status"})
@websocket_api.async_response
async def ws_get_status(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    await async_setup_firmware_manager(hass)
    _mgr = get_firmware_manager(hass)
    if _mgr is not None:
        await _mgr.async_refresh_catalog()  # TTL-gated no-op when fresh
    connection.send_result(msg["id"], _collect_status(hass))


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/set_zone",
        vol.Required("entity_id"): str,
        vol.Optional("temperature"): vol.Coerce(float),
        vol.Optional("hvac_mode"): str,
        vol.Optional("preset_mode"): str,
    }
)
@websocket_api.async_response
async def ws_set_zone(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    entity_id = msg["entity_id"]
    if not entity_id.startswith("climate."):
        connection.send_error(msg["id"], "invalid_entity", "Not a climate entity")
        return
    # Only allow controlling HCC zone entities, not arbitrary climate.*
    owned = False
    for data in (hass.data.get(DOMAIN) or {}).values():
        if not isinstance(data, dict) or "controller" not in data:
            continue
        for z in getattr(data["controller"], "zones", []) or []:
            if getattr(z, "entity_id", None) == entity_id:
                owned = True
                break
        if owned:
            break
    if not owned:
        connection.send_error(
            msg["id"], "invalid_entity", "Not a Home Climate Control zone"
        )
        return

    if "temperature" in msg:
        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": entity_id, "temperature": msg["temperature"]},
            blocking=True,
        )
    if "hvac_mode" in msg:
        await hass.services.async_call(
            "climate",
            "set_hvac_mode",
            {"entity_id": entity_id, "hvac_mode": msg["hvac_mode"]},
            blocking=True,
        )
    if "preset_mode" in msg:
        await hass.services.async_call(
            "climate",
            "set_preset_mode",
            {"entity_id": entity_id, "preset_mode": msg["preset_mode"]},
            blocking=True,
        )

    connection.send_result(msg["id"], {"ok": True, "status": _collect_status(hass)})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/calibrate_zone",
        vol.Required("action"): vol.In(["start", "cancel"]),
        vol.Optional("zone"): str,
        vol.Optional("entity_id"): str,
    }
)
@websocket_api.async_response
async def ws_calibrate_zone(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Start or cancel a bootstrap heat-rate calibration for one room."""
    controller = None
    if msg["action"] == "start":
        zone = msg.get("zone")
        if not zone:
            connection.send_error(msg["id"], "invalid", "zone required to start")
            return
        for data in (hass.data.get(DOMAIN) or {}).values():
            if isinstance(data, dict) and "controller" in data:
                candidate = data["controller"]
                names = [
                    getattr(z, "name", None) for z in getattr(candidate, "zones", [])
                ]
                if zone in names:
                    controller = candidate
                    break
        if controller is None:
            connection.send_error(msg["id"], "not_found", "Unknown zone")
            return
    else:
        # Cancel: any controller with an active calibration session.
        for data in (hass.data.get(DOMAIN) or {}).values():
            if not isinstance(data, dict) or "controller" not in data:
                continue
            candidate = data["controller"]
            cal = getattr(candidate, "calibration", None)
            if cal is not None and getattr(cal, "active", lambda: False)():
                controller = candidate
                break
        if controller is None:
            # Fall back: cancel on first controller (no-op if idle).
            for data in (hass.data.get(DOMAIN) or {}).values():
                if isinstance(data, dict) and "controller" in data:
                    controller = data["controller"]
                    break
        if controller is None:
            connection.send_error(msg["id"], "not_found", "No controller")
            return

    try:
        if msg["action"] == "start":
            result = await controller.async_start_calibration(msg["zone"])
        else:
            result = await controller.async_cancel_calibration()
    except (ValueError, RuntimeError) as err:
        connection.send_error(msg["id"], "calibration_error", str(err))
        return

    connection.send_result(msg["id"], {**result, "status": _collect_status(hass)})


def _zone_entry_and_names(hass: HomeAssistant, zone_name: str):
    """Find the config entry owning *zone_name*; returns (entry, names) or (None, [])."""
    for entry_id, data in (hass.data.get(DOMAIN) or {}).items():
        if not isinstance(data, dict) or "controller" not in data:
            continue
        names = [
            getattr(z, "name", None) for z in getattr(data["controller"], "zones", [])
        ]
        if zone_name in names:
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry is not None:
                return entry, names
    return None, []


# ── Editable integration options from the app Settings tab ────────────────
# Whitelist: only these keys may be written via home_climate_control/set_options.
# Numbers are (min, max) ranges; entity fields enforce domain prefixes;
# empty string/None on an optional entity field removes it from options.
_OPTION_RANGES: dict[str, tuple[float, float]] = {
    "min_flow_temp": (10.0, 90.0),
    "max_flow_temp": (20.0, 95.0),
    "curve_coeff": (0.2, 3.0),
    "wind_max_delta": (1.0, 6.0),
    "boiler_min_modulation": (5.0, 80.0),
    "rated_heat_input_kw": (0.0, 200.0),
    "min_heat_input_kw": (0.0, 200.0),
    "nomod_duty_factor": (0.1, 1.0),
    "gas_calibration": (0.2, 5.0),
    "gas_price_per_kwh": (0.0, 100.0),
}
_OPTION_BOOLS = (
    "autotune_curve",
    "learn_setbacks",
    "wind_compensation",
    "duty_cycle_enabled",
    "occupancy_enabled",
)
_OPTION_ENTITY_SINGLE: dict[str, tuple[str, ...]] = {
    "outdoor_sensor": ("sensor.", "weather."),
    "wind_entity": ("weather.",),
    "schedule_entity": ("schedule.", "input_select.", "sensor.", "input_text."),
}
_OPTION_ENTITY_MULTI: dict[str, tuple[str, ...]] = {
    "occupancy_trackers": ("device_tracker.", "person.", "binary_sensor."),
}
_OPTION_PRESETS = (
    "schedule_on_preset",
    "schedule_off_preset",
    "occupancy_away_preset",
    "occupancy_home_preset",
)

_OPTION_VIEW_DEFAULTS = {
    "curve_coeff": DEFAULT_CURVE_COEFF,
    "autotune_curve": True,
    "learn_setbacks": True,
    "min_flow_temp": DEFAULT_MIN_FLOW_TEMP,
    "max_flow_temp": DEFAULT_MAX_FLOW_TEMP,
    "boiler_min_modulation": DEFAULT_BOILER_MIN_MODULATION,
    "duty_cycle_enabled": True,
    "wind_max_delta": DEFAULT_WIND_MAX_DELTA,
    "schedule_on_preset": PRESET_COMFORT,
    "schedule_off_preset": PRESET_ECO,
    "occupancy_enabled": False,
    "occupancy_trackers": [],
    "occupancy_away_preset": PRESET_AWAY,
    "occupancy_home_preset": PRESET_COMFORT,
    "rated_heat_input_kw": 24.0,
    "min_heat_input_kw": 0.0,
    "nomod_duty_factor": 0.6,
    "gas_calibration": 1.0,
}


def _options_view(opts: dict) -> dict:
    """Effective editable-option values (defaults applied) for the panel."""
    view = {}
    for key, default in _OPTION_VIEW_DEFAULTS.items():
        val = opts.get(key, default)
        view[key] = val
    for key in ("outdoor_sensor", "wind_entity", "schedule_entity"):
        view[key] = opts.get(key)
    view["wind_compensation"] = opts.get(
        CONF_WIND_ENABLED, bool(opts.get(CONF_WIND_ENTITY))
    )
    view["gas_price_per_kwh"] = opts.get("gas_price_per_kwh")
    return view


def _primary_entry(hass: HomeAssistant):
    """The config entry whose controller is loaded (else first of domain)."""
    for entry_id, data in (hass.data.get(DOMAIN) or {}).items():
        if isinstance(data, dict) and "controller" in data:
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry is not None:
                return entry
    for entry in hass.config_entries.async_entries(DOMAIN):
        return entry
    return None


# Home Assistant's websocket_command decorator expects the raw schema
# mapping and reads schema.validators[0].schema["type"] itself. Do not wrap
# this in vol.Schema here; HA performs that wrapping internally.
_SET_OPTIONS_SCHEMA = {
    vol.Required("type"): f"{DOMAIN}/set_options",
    vol.Optional("id"): int,
    **{
        vol.Optional(key): vol.Any(
            str, float, int, bool, list, dict, type(None)
        )
        for key in (
            set(_OPTION_RANGES)
            | set(_OPTION_BOOLS)
            | set(_OPTION_ENTITY_SINGLE)
            | set(_OPTION_ENTITY_MULTI)
            | set(_OPTION_PRESETS)
        )
    },
}


@websocket_api.require_admin
@websocket_api.websocket_command(_SET_OPTIONS_SCHEMA)
@websocket_api.async_response
async def ws_set_options(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Edit integration options from the app Settings tab.

    Only whitelisted keys are accepted; numbers are range-checked, entity
    fields must carry the right domain prefix, presets must be valid. An
    empty value on an optional entity field removes it. Unknown keys are
    rejected (the panel never sends them).
    """
    entry = _primary_entry(hass)
    if entry is None:
        connection.send_error(msg["id"], "not_found", "No configured system")
        return

    patch: dict[str, Any] = {}
    pop_keys: list[str] = []

    def _err(code: str, text: str) -> None:
        connection.send_error(msg["id"], code, text)

    for key, raw in msg.items():
        if key in ("id", "type"):
            continue
        if key not in (
            set(_OPTION_RANGES) | set(_OPTION_BOOLS)
            | set(_OPTION_ENTITY_SINGLE) | set(_OPTION_ENTITY_MULTI)
            | set(_OPTION_PRESETS)
        ):
            _err("unknown_option", f"Key not editable: {key}")
            return
        if key in _OPTION_RANGES:
            try:
                val = float(raw)
            except (TypeError, ValueError):
                _err("invalid_value", f"{key} must be a number")
                return
            lo, hi = _OPTION_RANGES[key]
            if not lo <= val <= hi:
                _err("invalid_value", f"{key} must be between {lo} and {hi}")
                return
            patch[key] = val
        elif key in _OPTION_BOOLS:
            patch[key] = bool(raw)
        elif key in _OPTION_ENTITY_SINGLE:
            text = (str(raw) if raw is not None else "").strip()
            if not text:
                pop_keys.append(key)
                continue
            if not text.startswith(_OPTION_ENTITY_SINGLE[key]):
                _err("invalid_entity", f"{key} must be one of {', '.join(_OPTION_ENTITY_SINGLE[key])}*")
                return
            patch[key] = text
        elif key in _OPTION_ENTITY_MULTI:
            items = raw if isinstance(raw, list) else []
            cleaned = []
            for item in items:
                text = str(item).strip()
                if text and text.startswith(_OPTION_ENTITY_MULTI[key]):
                    cleaned.append(text)
            if not cleaned:
                pop_keys.append(key)
            else:
                patch[key] = cleaned
        elif key in _OPTION_PRESETS:
            if raw not in ZONE_PRESETS:
                _err("invalid_value", f"{key} must be one of {', '.join(ZONE_PRESETS)}")
                return
            patch[key] = raw

    mn = patch.get("min_flow_temp", (entry.options or {}).get("min_flow_temp"))
    mx = patch.get("max_flow_temp", (entry.options or {}).get("max_flow_temp"))
    if mn is not None and mx is not None and float(mn) >= float(mx):
        _err("min_flow_above_max", "Min flow must be below max flow")
        return

    options = {**(entry.options or {}), **patch}
    for key in pop_keys:
        options.pop(key, None)

    hass.config_entries.async_update_entry(entry, options=options)
    await hass.config_entries.async_reload(entry.entry_id)
    connection.send_result(msg["id"], {"ok": True, "status": _collect_status(hass)})


def validate_zone_name(names: list[str | None], new_name: str) -> str | None:
    """Returns an error string, or None when the name is acceptable."""
    name = (new_name or "").strip()
    if not name:
        return "Room name cannot be empty"
    if len(name) > 40:
        return "Room name too long (max 40 characters)"
    lowered = [str(n).strip().lower() for n in names if n]
    if name.lower() in lowered:
        return f"A room named '{name}' already exists"
    return None


FLOOR_MAX = 30
HEAT_CONTROLS = ("smart", "manual")


def build_zone_config(
    names: list[str | None],
    *,
    name: str,
    heat_control: str = HEAT_CONTROL_SMART,
    floor: int = 0,
    trv_climates: list[str] | None = None,
    temp_sensor: str | None = None,
    window_sensors: list[str] | None = None,
    lux_sensor: str | None = None,
    co2_sensor: str | None = None,
    trv_position_entity: str | None = None,
    radiator_kw: float | None = None,
) -> dict[str, Any]:
    """Validate a new-room request; returns the zone dict or raises ValueError.

    Mirrors the config flow's zone step: a controlled (smart) room needs at
    least one addressable TRV; a manual-radiator room legitimately has none.
    """
    name = (name or "").strip()
    err = validate_zone_name(names, name)
    if err:
        raise ValueError(err)
    if heat_control not in HEAT_CONTROLS:
        raise ValueError("heat_control must be 'smart' or 'manual'")
    floor = max(0, min(FLOOR_MAX, int(floor or 0)))
    trvs = [t.strip() for t in (trv_climates or []) if t and t.strip()]
    if heat_control == HEAT_CONTROL_SMART and not trvs:
        raise ValueError("A smart room needs at least one TRV climate entity")
    for t in trvs:
        if not t.startswith("climate."):
            raise ValueError(f"'{t}' is not a climate entity")
    sensor = (temp_sensor or "").strip() or None
    if sensor and not sensor.startswith("sensor."):
        raise ValueError(f"'{sensor}' is not a sensor entity")
    windows = [w.strip() for w in (window_sensors or []) if w and w.strip()]
    lux = (lux_sensor or "").strip() or None
    if lux and not lux.startswith("sensor."):
        raise ValueError(f"'{lux}' is not a sensor entity")
    co2 = (co2_sensor or "").strip() or None
    if co2 and not co2.startswith("sensor."):
        raise ValueError(f"'{co2}' is not a sensor entity")
    valve = (trv_position_entity or "").strip() or None
    if valve and not valve.startswith(("sensor.", "number.")):
        raise ValueError(f"'{valve}' is not a sensor or number entity")
    if radiator_kw is not None:
        try:
            radiator_kw = float(radiator_kw)
        except (TypeError, ValueError):
            raise ValueError("radiator_kw must be a number")
        if not 0 <= radiator_kw <= 20:
            raise ValueError("radiator_kw must be between 0 and 20")
    cfg = {
        CONF_ZONE_NAME: name,
        CONF_ZONE_TRV_CLIMATES: trvs,
        CONF_ZONE_TEMP_SENSOR: sensor,
        CONF_ZONE_WINDOW_SENSORS: windows,
        CONF_ZONE_FLOOR: floor,
        CONF_ZONE_HEAT_CONTROL: heat_control,
        "setpoint": DEFAULT_ZONE_SETPOINT,
    }
    if lux:
        cfg[CONF_ZONE_LUX_SENSOR] = lux
    if co2:
        cfg[CONF_ZONE_CO2_SENSOR] = co2
    if valve:
        cfg[CONF_ZONE_TRV_POSITION] = valve
    if radiator_kw:
        cfg[CONF_ZONE_RADIATOR_KW] = radiator_kw
    return cfg


def validate_zone_update(
    names: list[str | None],
    *,
    new_name: str | None = None,
    floor: int | None = None,
    heat_control: str | None = None,
    device_fields: bool = False,
) -> str | None:
    """Validate any combination of room edits; error string or None."""
    if (
        new_name is None
        and floor is None
        and heat_control is None
        and not device_fields
    ):
        return "Nothing to change"
    if new_name is not None:
        err = validate_zone_name(names, new_name)
        if err:
            return err
    if floor is not None and not (0 <= int(floor) <= FLOOR_MAX):
        return f"Floor must be between 0 and {FLOOR_MAX}"
    if heat_control is not None and heat_control not in HEAT_CONTROLS:
        return "heat_control must be 'smart' or 'manual'"
    return None


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/rename_zone",
        vol.Required("zone"): str,
        vol.Optional("new_name"): str,
        vol.Optional("floor"): vol.All(vol.Coerce(int), vol.Range(min=0, max=FLOOR_MAX)),
        vol.Optional("heat_control"): vol.In(HEAT_CONTROLS),
        vol.Optional("trv_climates"): [str],
        vol.Optional("temp_sensor"): vol.Any(str, None),
        vol.Optional("window_sensors"): [str],
        vol.Optional("lux_sensor"): vol.Any(str, None),
        vol.Optional("co2_sensor"): vol.Any(str, None),
        vol.Optional("trv_position_entity"): vol.Any(str, None),
        vol.Optional("radiator_kw"): vol.Any(vol.Coerce(float), None),
    }
)
@websocket_api.async_response
async def ws_rename_zone(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Update a room: rename and/or set floor / heater-control / devices.

    Any rename migrates learned history to the new key first; the options
    update reloads platforms so changes apply live.
    """
    entry, names = _zone_entry_and_names(hass, msg["zone"])
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Unknown zone")
        return

    new_name = (msg.get("new_name") or "").strip() or None
    floor = msg.get("floor")
    heat_control = msg.get("heat_control")
    trv_climates = msg.get("trv_climates")
    temp_sensor = msg.get("temp_sensor")
    window_sensors = msg.get("window_sensors")
    lux_sensor = msg.get("lux_sensor")
    co2_sensor = msg.get("co2_sensor")
    trv_position_entity = msg.get("trv_position_entity")
    radiator_kw = msg.get("radiator_kw")
    device_fields = (
        trv_climates is not None
        or "temp_sensor" in msg
        or window_sensors is not None
        or "lux_sensor" in msg
        or "co2_sensor" in msg
        or "trv_position_entity" in msg
        or "radiator_kw" in msg
    )
    err = validate_zone_update(
        [n for n in names if n != msg["zone"]],
        new_name=new_name,
        floor=floor,
        heat_control=heat_control,
        device_fields=device_fields,
    )
    if err is not None:
        connection.send_error(msg["id"], "invalid_name", err)
        return

    controller = hass.data[DOMAIN][entry.entry_id]["controller"]
    zones_cfg = list(entry.options.get(CONF_ZONES, []))
    new_zones = []
    for z in zones_cfg:
        if z.get(CONF_ZONE_NAME) != msg["zone"]:
            new_zones.append(z)
            continue
        z = dict(z)
        if new_name:
            z[CONF_ZONE_NAME] = new_name
        if floor is not None:
            z[CONF_ZONE_FLOOR] = int(floor)
        if heat_control is not None:
            z[CONF_ZONE_HEAT_CONTROL] = heat_control
        if trv_climates is not None:
            trvs = [t.strip() for t in trv_climates if t and t.strip()]
            for t in trvs:
                if not t.startswith("climate."):
                    connection.send_error(
                        msg["id"], "invalid_zone", f"'{t}' is not a climate entity"
                    )
                    return
            z[CONF_ZONE_TRV_CLIMATES] = trvs
        if "temp_sensor" in msg:
            sensor = (temp_sensor or "").strip() or None
            if sensor and not sensor.startswith("sensor."):
                connection.send_error(
                    msg["id"], "invalid_zone", f"'{sensor}' is not a sensor entity"
                )
                return
            if sensor:
                z[CONF_ZONE_TEMP_SENSOR] = sensor
            else:
                z.pop(CONF_ZONE_TEMP_SENSOR, None)
        if window_sensors is not None:
            z[CONF_ZONE_WINDOW_SENSORS] = [
                w.strip() for w in window_sensors if w and w.strip()
            ]
        if "lux_sensor" in msg:
            lux = (lux_sensor or "").strip() or None
            if lux and not lux.startswith("sensor."):
                connection.send_error(
                    msg["id"], "invalid_zone", f"'{lux}' is not a sensor entity"
                )
                return
            if lux:
                z[CONF_ZONE_LUX_SENSOR] = lux
            else:
                z.pop(CONF_ZONE_LUX_SENSOR, None)
        if "co2_sensor" in msg:
            co2 = (co2_sensor or "").strip() or None
            if co2 and not co2.startswith("sensor."):
                connection.send_error(
                    msg["id"], "invalid_zone", f"'{co2}' is not a sensor entity"
                )
                return
            if co2:
                z[CONF_ZONE_CO2_SENSOR] = co2
            else:
                z.pop(CONF_ZONE_CO2_SENSOR, None)
        if "trv_position_entity" in msg:
            valve = (trv_position_entity or "").strip() or None
            if valve and not valve.startswith(("sensor.", "number.")):
                connection.send_error(
                    msg["id"], "invalid_zone",
                    f"'{valve}' is not a sensor or number entity",
                )
                return
            if valve:
                z[CONF_ZONE_TRV_POSITION] = valve
            else:
                z.pop(CONF_ZONE_TRV_POSITION, None)
        if "radiator_kw" in msg:
            if radiator_kw is None:
                z.pop(CONF_ZONE_RADIATOR_KW, None)
            else:
                try:
                    rkw = float(radiator_kw)
                except (TypeError, ValueError):
                    connection.send_error(
                        msg["id"], "invalid_zone", "radiator_kw must be a number"
                    )
                    return
                if not 0 <= rkw <= 20:
                    connection.send_error(
                        msg["id"], "invalid_zone",
                        "radiator_kw must be between 0 and 20",
                    )
                    return
                z[CONF_ZONE_RADIATOR_KW] = rkw
        new_zones.append(z)
    new_options = {**entry.options, CONF_ZONES: new_zones}
    # Migrate learned history before the reload swaps the entity out.
    if new_name:
        controller.rename_zone_learning(msg["zone"], new_name)
    hass.config_entries.async_update_entry(entry, options=new_options)
    await hass.config_entries.async_reload(entry.entry_id)
    connection.send_result(msg["id"], {"ok": True, "status": _collect_status(hass)})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/add_zone",
        vol.Required("name"): str,
        vol.Optional("heat_control", default=HEAT_CONTROL_SMART): vol.In(HEAT_CONTROLS),
        vol.Optional("floor", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=FLOOR_MAX)),
        vol.Optional("trv_climates", default=[]): [str],
        vol.Optional("temp_sensor"): str,
        vol.Optional("window_sensors", default=[]): [str],
        vol.Optional("lux_sensor"): str,
        vol.Optional("co2_sensor"): str,
        vol.Optional("trv_position_entity"): str,
        vol.Optional("radiator_kw"): vol.Any(vol.Coerce(float), None),
    }
)
@websocket_api.async_response
async def ws_add_zone(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Create a room from the panel; the options reload adds its entity."""
    # Any configured entry owns the room list (single-install typical).
    entry = None
    existing: list[str | None] = []
    for entry_id, data in (hass.data.get(DOMAIN) or {}).items():
        if isinstance(data, dict) and "controller" in data:
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry is not None:
                existing = [
                    getattr(z, "name", None)
                    for z in getattr(data["controller"], "zones", [])
                ]
                break
    if entry is None:
        connection.send_error(msg["id"], "not_found", "No configured system found")
        return

    try:
        zone = build_zone_config(
            existing,
            name=msg["name"],
            heat_control=msg["heat_control"],
            floor=msg["floor"],
            trv_climates=msg["trv_climates"],
            temp_sensor=msg.get("temp_sensor"),
            window_sensors=msg["window_sensors"],
            lux_sensor=msg.get("lux_sensor"),
            co2_sensor=msg.get("co2_sensor"),
            trv_position_entity=msg.get("trv_position_entity"),
            radiator_kw=msg.get("radiator_kw"),
        )
    except ValueError as err:
        connection.send_error(msg["id"], "invalid_zone", str(err))
        return

    zones_cfg = list(entry.options.get(CONF_ZONES, []))
    zones_cfg.append(zone)
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_ZONES: zones_cfg}
    )
    await hass.config_entries.async_reload(entry.entry_id)
    connection.send_result(msg["id"], {"ok": True, "status": _collect_status(hass)})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/remove_zone",
        vol.Required("zone"): str,
    }
)
@websocket_api.async_response
async def ws_remove_zone(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Remove a room card: drops it from options; the entry reload cleans up."""
    entry, _names = _zone_entry_and_names(hass, msg["zone"])
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Unknown zone")
        return
    zones_cfg = list(entry.options.get(CONF_ZONES, []))
    new_zones = [z for z in zones_cfg if z.get(CONF_ZONE_NAME) != msg["zone"]]
    if len(new_zones) == len(zones_cfg):
        connection.send_error(msg["id"], "not_found", "Unknown zone")
        return
    if not new_zones:
        connection.send_error(
            msg["id"], "last_zone", "Cannot remove the last remaining room"
        )
        return
    new_options = {**entry.options, CONF_ZONES: new_zones}
    hass.config_entries.async_update_entry(entry, options=new_options)
    await hass.config_entries.async_reload(entry.entry_id)
    connection.send_result(msg["id"], {"ok": True, "status": _collect_status(hass)})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/set_failsafe",
        vol.Required("enable"): bool,
        vol.Required("flow"): vol.All(vol.Coerce(float), vol.Range(min=10, max=90)),
        vol.Required("grace_min"): vol.All(vol.Coerce(int), vol.Range(min=1, max=120)),
    }
)
@websocket_api.async_response
async def ws_set_failsafe(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Push connection-loss failsafe values to the HCS device (persisted there)."""
    backend = None
    for data in hass.data.get(DOMAIN, {}).values():
        if not isinstance(data, dict):
            continue
        cand = data.get("backend")
        if cand is not None and hasattr(cand, "async_set_failsafe_cfg"):
            backend = cand
            break
    if backend is None:
        connection.send_error(
            msg["id"], "no_backend", "Failsafe requires the Home Climate System backend"
        )
        return
    await backend.async_set_failsafe_cfg(
        msg["enable"], msg["flow"], msg["grace_min"]
    )
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/list_devices"})
@websocket_api.async_response
async def ws_list_devices(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    mgr = await async_setup_firmware_manager(hass)
    await mgr.async_refresh_catalog()  # TTL-gated no-op when fresh
    connection.send_result(
        msg["id"],
        {"devices": mgr.list_devices(), "catalog": mgr.catalog},
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/forget_device",
        vol.Required("node_id"): str,
    }
)
@websocket_api.async_response
async def ws_forget_device(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Remove a board from the Firmware tab list (wipes retained MQTT)."""
    mgr = await async_setup_firmware_manager(hass)
    result = await mgr.async_forget(msg["node_id"])
    if not result.get("ok"):
        connection.send_error(msg["id"], "forget_failed", result.get("error", "?"))
        return
    connection.send_result(msg["id"], {"ok": True, "devices": mgr.list_devices()})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/ping_devices"})
@websocket_api.async_response
async def ws_ping_devices(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    mgr = await async_setup_firmware_manager(hass)
    await mgr.async_ping()
    connection.send_result(msg["id"], {"ok": True, "devices": mgr.list_devices()})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/device_control",
        vol.Required("node_id"): str,
        vol.Required("key"): str,
        vol.Optional("value"): vol.Any(bool, int, float, str, None),
        vol.Optional("curve"): dict,
    }
)
@websocket_api.async_response
async def ws_device_control(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    mgr = await async_setup_firmware_manager(hass)
    if msg.get("curve") is not None:
        result = await mgr.async_apply_wc_curve(msg["node_id"], msg["curve"])
    else:
        result = await mgr.async_send_control(msg["node_id"], msg["key"], msg.get("value"))
    if not result.get("ok"):
        connection.send_error(
            msg["id"], "control_failed", result.get("error") or "failed"
        )
        return
    connection.send_result(msg["id"], result)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/set_device_settings",
        vol.Required("node_id"): str,
        vol.Required("settings"): dict,
    }
)
@websocket_api.async_response
async def ws_set_device_settings(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    mgr = await async_setup_firmware_manager(hass)
    result = await mgr.async_push_settings(msg["node_id"], msg["settings"])
    if not result.get("ok"):
        connection.send_error(
            msg["id"], "settings_failed", result.get("error") or "failed"
        )
        return
    connection.send_result(msg["id"], result)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/flash_device",
        vol.Required("node_id"): str,
        vol.Optional("url"): str,
        vol.Optional("catalog_id"): str,
        vol.Optional("force"): bool,
    }
)
@websocket_api.async_response
async def ws_flash_device(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    mgr = await async_setup_firmware_manager(hass)
    url = msg.get("url") or ""
    if url:
        from urllib.parse import urlsplit

        scheme = urlsplit(url).scheme.lower()
        if scheme not in ("http", "https"):
            connection.send_error(
                msg["id"], "bad_url", f"Unsupported url scheme: {scheme or 'none'}"
            )
            return
    catalog_id = msg.get("catalog_id")
    item = None
    if catalog_id:
        item = catalog_item(mgr.catalog, catalog_id)
        if item and not url:
            url = item.get("url") or ""
        elif item is None:
            connection.send_error(
                msg["id"], "unknown_catalog_id", f"No such firmware: {catalog_id}"
            )
            return
    if not url:
        connection.send_error(msg["id"], "missing_url", "Provide url or catalog_id")
        return

    # Board guard: refuse images built for another board unless forced.
    # Prefix match allows e.g. lolin_c3_mini_gw image on lolin_c3_mini.
    dev = mgr.devices.get(msg["node_id"])
    if (
        item
        and dev is not None
        and dev.board
        and item.get("board")
        and dev.board != item["board"]
        and not dev.board.startswith(item["board"])
        and not item["board"].startswith(dev.board)
        and not msg.get("force", False)
    ):
        connection.send_error(
            msg["id"],
            "board_mismatch",
            f"Image is for '{item['board']}' but device reports "
            f"'{dev.board}'. Pass force=true to flash anyway.",
        )
        return

    result = await mgr.async_trigger_ota(
        msg["node_id"], url, target_version=(item or {}).get("version")
    )
    if not result.get("ok"):
        connection.send_error(
            msg["id"], "flash_failed", result.get("error") or "flash failed"
        )
        return
    connection.send_result(msg["id"], result)


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/reboot_device",
        vol.Required("node_id"): str,
    }
)
@websocket_api.async_response
async def ws_reboot_device(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    mgr = await async_setup_firmware_manager(hass)
    if msg["node_id"] not in mgr.devices:
        connection.send_error(
            msg["id"], "unknown_node", f"No such device: {msg['node_id']}"
        )
        return
    result = await mgr.async_reboot(msg["node_id"])
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/firmware_catalog"})
@websocket_api.async_response
async def ws_firmware_catalog(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    mgr = await async_setup_firmware_manager(hass)
    connection.send_result(msg["id"], {"catalog": mgr.catalog})


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/get_boiler_catalog"}
)
@websocket_api.async_response
async def ws_get_boiler_catalog(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Manufacturer/model catalog for the panel dropdowns."""
    from .boilers import catalog_payload

    connection.send_result(msg["id"], catalog_payload())


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/set_boiler_info",
        vol.Optional("make"): str,
        vol.Optional("model"): str,
    }
)
@websocket_api.async_response
async def ws_set_boiler_info(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Persist the manually selected boiler make/model."""
    from .boiler_info import get_boiler_info

    bi = get_boiler_info(hass)
    if bi is None:
        connection.send_error(msg["id"], "not_ready", "Boiler info not set up")
        return
    await bi.async_set_selection(msg.get("make"), msg.get("model"))
    connection.send_result(msg["id"], {"ok": True, "info": bi.as_dict()})


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/check_updates"}
)
@websocket_api.async_response
async def ws_check_updates(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Force an immediate firmware-update check against GitHub releases."""
    from .update_checker import get_update_checker

    uc = get_update_checker(hass)
    if uc is None:
        connection.send_error(msg["id"], "not_ready", "Checker not started")
        return
    info = await uc.async_check(force=True)
    connection.send_result(msg["id"], {"ok": True, "info": info})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/set_github_token",
        vol.Optional("token"): str,
    }
)
@websocket_api.async_response
async def ws_set_github_token(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Store an optional personal access token (raises the API rate limit)."""
    from .update_checker import get_update_checker

    uc = get_update_checker(hass)
    if uc is None:
        connection.send_error(msg["id"], "not_ready", "Checker not started")
        return
    await uc.async_set_token(msg.get("token"))
    connection.send_result(msg["id"], {"ok": True})


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/get_ot_log",
        vol.Required("node_id"): str,
        vol.Optional("clear", default=False): bool,
    }
)
@websocket_api.async_response
async def ws_get_ot_log(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    mgr = await async_setup_firmware_manager(hass)
    result = await mgr.async_get_ot_log(msg["node_id"], msg["clear"])
    connection.send_result(msg["id"], result)
