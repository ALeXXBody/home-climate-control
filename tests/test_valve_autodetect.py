"""Auto-detection of TRV valve-position entities + panel popup."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.home_climate_control.const import (
    CONF_ZONE_NAME,
    CONF_ZONE_TRV_CLIMATES,
    CONF_ZONE_TRV_POSITION,
    CONF_ZONES,
    DOMAIN,
)
from custom_components.home_climate_control.websocket_api import (
    _detect_trv_position_entity,
    ws_add_zone,
    ws_rename_zone,
)

ENTRY_ID = "entry-hcc-1"


class _St:
    """Minimal state object mimic for hass.states.async_all."""

    def __init__(self, entity_id, unit="", friendly=""):
        self.entity_id = entity_id
        self.attributes = {"friendly_name": friendly}
        if unit:
            self.attributes["unit_of_measurement"] = unit


def _hass(states):
    hass = MagicMock()
    hass.states.async_all = MagicMock(return_value=states)
    return hass


# ── detector ─────────────────────────────────────────────────────────


def test_detect_prefers_trv_slug_opening_degree():
    hass = _hass([
        _St("number.conservatory_trv_valve_closing_degree"),
        _St("number.conservatory_trv_valve_opening_degree", "%",
            "Conservatory TRV valve opening"),
        _St("number.kitchen_trv_valve_opening_degree", "%"),
        _St("sensor.outdoor_temperature", "°C"),
    ])
    got = _detect_trv_position_entity(
        hass, "Conservatory", ["climate.conservatory_trv"]
    )
    assert got == "number.conservatory_trv_valve_opening_degree"


def test_detect_room_slug_fallback_when_no_trv_slug():
    hass = _hass([
        _St("number.outside_valve_opening", "%"),
        _St("number.office_valve_opening", "%"),
    ])
    got = _detect_trv_position_entity(hass, "Office", [])
    assert got == "number.office_valve_opening"


def test_detect_rejects_degree_unit_and_unlinked_valves():
    hass = _hass([
        _St("number.random_thing_valve", "°C"),
        _St("number.kitchen_trv_valve_opening_degree", "%"),
    ])
    got = _detect_trv_position_entity(
        hass, "Conservatory", ["climate.conservatory_trv"]
    )
    assert got is None


def test_detect_returns_none_with_no_states():
    got = _detect_trv_position_entity(_hass([]), "Office", ["climate.x_trv"])
    assert got is None


# ── wiring: add / edit auto-populate ─────────────────────────────────


def _wired_hass(states):
    """hass wired like test_zone_ws_handlers for ws_add_zone."""
    hass = _hass(states)
    ctrl = MagicMock()
    ctrl.zones = []
    ctrl.diagnostics = lambda: {}
    ctrl.outdoor_temp = lambda: 5.0
    ctrl.flow_setpoint = 50.0
    ctrl.total_demand = 0.0
    ctrl.active_zone_names = []
    ctrl.curve_coeff = 1.0
    ctrl.min_flow = 30.0
    ctrl.max_flow = 70.0
    entry = MagicMock()
    entry.entry_id = ENTRY_ID
    zones = []
    entry.options = {CONF_ZONES: zones}
    entry.async_reload = AsyncMock()
    hass.data = {
        DOMAIN: {
            ENTRY_ID: {
                "controller": ctrl,
                "backend": MagicMock(),
                "backend_type": "hcs",
                "zones_cfg": [],
                "firmware_manager": None,
            },
        },
    }
    hass.config_entries.async_entries = MagicMock(return_value=[entry])
    hass.config_entries.async_get_entry = MagicMock(return_value=entry)
    hass.config_entries.async_update_entry = MagicMock()
    hass.config_entries.async_reload = AsyncMock()
    hass.states.get = MagicMock(return_value=None)
    return hass, entry


def test_ws_add_zone_autofills_detected_valve_entity():
    hass, entry = _wired_hass([
        _St("number.office_trv_valve_opening_degree", "%"),
    ])
    conn = MagicMock()
    msg = {
        "id": 1,
        "name": "Office",
        "heat_control": "valve",
        "floor": 0,
        "trv_climates": ["climate.office_trv"],
        "window_sensors": [],
    }
    asyncio.run(ws_add_zone(hass, conn, msg))

    conn.send_error.assert_not_called()
    saved = hass.config_entries.async_update_entry.call_args.kwargs[
        "options"
][CONF_ZONES][-1]
    assert (
        saved[CONF_ZONE_TRV_POSITION]
        == "number.office_trv_valve_opening_degree"
    )


def test_ws_add_zone_explicit_valve_wins_over_detection():
    hass, entry = _wired_hass([
        _St("number.office_trv_valve_opening_degree", "%"),
        _St("number.other_valve_opening", "%"),
    ])
    conn = MagicMock()
    msg = {
        "id": 1, "name": "Office", "heat_control": "valve", "floor": 0,
        "trv_climates": ["climate.office_trv"],
        "trv_position_entity": "number.other_valve_opening",
        "window_sensors": [],
    }
    asyncio.run(ws_add_zone(hass, conn, msg))
    saved = hass.config_entries.async_update_entry.call_args.kwargs[
        "options"
][CONF_ZONES][-1]
    assert saved[CONF_ZONE_TRV_POSITION] == "number.other_valve_opening"


def test_rename_zone_autofills_valve_when_trv_added():
    zones_cfg = [
        {CONF_ZONE_NAME: "Office", CONF_ZONE_TRV_CLIMATES: []},
    ]
    entry = MagicMock()
    entry.entry_id = ENTRY_ID
    entry.options = {CONF_ZONES: zones_cfg}
    entry.async_reload = AsyncMock()
    entry.async_on_unload = MagicMock()
    ctrl = MagicMock()
    ctrl.zones = []
    hass = _hass([_St("number.office_trv_valve_opening_degree", "%")])
    hass.data = {
        DOMAIN: {ENTRY_ID: {"controller": ctrl}},
    }
    hass.config_entries.async_entries = MagicMock(return_value=[entry])
    hass.config_entries.async_get_entry = MagicMock(return_value=entry)
    hass.config_entries.async_update_entry = MagicMock()
    hass.config_entries.async_reload = AsyncMock()
    hass.states.get = MagicMock(return_value=None)

    conn = MagicMock()
    msg = {"id": 1, "zone": "Office", "trv_climates": ["climate.office_trv"]}
    asyncio.run(ws_rename_zone(hass, conn, msg))

    conn.send_error.assert_not_called()
    saved = hass.config_entries.async_update_entry.call_args.kwargs[
        "options"
][CONF_ZONES][0]
    assert (
        saved[CONF_ZONE_TRV_POSITION]
        == "number.office_trv_valve_opening_degree"
    )


# ── panel popup gates live in tests/panel_dom_test.mjs ───────────────


@pytest.mark.parametrize("n", [1])
def test_placeholder(n):
    assert n == 1
