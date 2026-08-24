"""WebSocket API for the Home Climate sidebar app."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN
from .firmware_manager import (
    async_setup_firmware_manager,
    catalog_item,
    get_firmware_manager,
)

_LOGGER = logging.getLogger(__name__)


@callback
def async_setup_websocket(hass: HomeAssistant) -> None:
    """Register WebSocket commands (once)."""
    key = f"{DOMAIN}_ws_registered"
    if hass.data.get(key):
        return
    websocket_api.async_register_command(hass, ws_get_status)
    websocket_api.async_register_command(hass, ws_set_zone)
    websocket_api.async_register_command(hass, ws_set_failsafe)
    websocket_api.async_register_command(hass, ws_get_boiler_catalog)
    websocket_api.async_register_command(hass, ws_set_boiler_info)
    websocket_api.async_register_command(hass, ws_check_updates)
    websocket_api.async_register_command(hass, ws_set_github_token)
    websocket_api.async_register_command(hass, ws_list_devices)
    websocket_api.async_register_command(hass, ws_ping_devices)
    websocket_api.async_register_command(hass, ws_flash_device)
    websocket_api.async_register_command(hass, ws_set_device_settings)
    websocket_api.async_register_command(hass, ws_reboot_device)
    websocket_api.async_register_command(hass, ws_firmware_catalog)
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
                    "state": state.state if state else None,
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
                "boiler_info": boiler_info,
                "update_info": update_info,
                "zones": zones_out,
            }
        )

    mgr = get_firmware_manager(hass)
    devices = mgr.list_devices() if mgr else []

    return {
        "domain": DOMAIN,
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


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/set_failsafe",
        vol.Required("enable"): bool,
        vol.Required("flow"): vol.Coerce(float),
        vol.Required("grace_min"): vol.Coerce(int),
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
