"""WebSocket API for the Home Climate sidebar app."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


@callback
def async_setup_websocket(hass: HomeAssistant) -> None:
    """Register WebSocket commands (once)."""
    key = f"{DOMAIN}_ws_registered"
    if hass.data.get(key):
        return
    websocket_api.async_register_command(hass, ws_get_status)
    websocket_api.async_register_command(hass, ws_set_zone)
    hass.data[key] = True


def _collect_status(hass: HomeAssistant) -> dict[str, Any]:
    """Build a snapshot of all HCC controllers for the UI."""
    store = hass.data.get(DOMAIN, {})
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
                "zones": zones_out,
            }
        )

    return {
        "domain": DOMAIN,
        "systems": systems,
        "support_url": "https://buymeacoffee.com/alexxbody",
        "docs": {
            "software": "https://github.com/ALeXXBody/home-climate-control",
            "hardware": "https://github.com/ALeXXBody/home-climate-system",
        },
    }


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/get_status"})
@websocket_api.async_response
async def ws_get_status(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return full system snapshot for the sidebar app."""
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
    """Apply zone changes via climate services."""
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
