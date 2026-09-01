"""Editable settings via home_climate_control/set_options."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

from custom_components.home_climate_control import websocket_api
from custom_components.home_climate_control.const import DOMAIN


def _make_hass():
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "e1"
    entry.options = {"min_flow_temp": 25.0, "max_flow_temp": 75.0}
    hass.config_entries.async_get_entry = lambda eid: entry
    hass.config_entries.async_entries.return_value = []
    hass.config_entries.async_reload = AsyncMock()
    hass.data = {DOMAIN: {"e1": {"controller": object(), "backend": object()}}}
    return hass, entry


def test_set_options_writes_and_returns_status():
    hass, entry = _make_hass()
    conn = MagicMock()
    msg = {"id": 5, "curve_coeff": 1.4, "wind_entity": "weather.home",
           "wind_compensation": True, "wind_max_delta": 2.5}
    res = asyncio.run(websocket_api.ws_set_options(hass, conn, msg))
    updated = hass.config_entries.async_update_entry.call_args
    assert updated.args[0] is entry
    opts = updated.kwargs["options"]
    assert opts["curve_coeff"] == 1.4
    assert opts["wind_entity"] == "weather.home"
    assert opts["wind_compensation"] is True
    assert opts["wind_max_delta"] == 2.5
    assert opts["min_flow_temp"] == 25.0  # untouched keys preserved
    hass.config_entries.async_reload.assert_awaited_once_with("e1")
    conn.send_result.assert_called_once()
    body = conn.send_result.call_args.args[1]
    assert body["ok"] is True
    assert "status" in body


def test_set_options_rejects_unknown_key():
    hass, _ = _make_hass()
    conn = MagicMock()
    asyncio.run(websocket_api.ws_set_options(
        hass, conn, {"id": 1, "nuclear_option": True}))
    conn.send_error.assert_called_once()
    assert conn.send_error.call_args.args[1] == "unknown_option"
    hass.config_entries.async_update_entry.assert_not_called()


def test_set_options_rejects_bad_entity_prefix():
    hass, _ = _make_hass()
    conn = MagicMock()
    asyncio.run(websocket_api.ws_set_options(
        hass, conn, {"id": 2, "wind_entity": "sensor.not_a_weather"}))
    conn.send_error.assert_called_once()
    assert conn.send_error.call_args.args[1] == "invalid_entity"


def test_set_options_rejects_out_of_range():
    hass, _ = _make_hass()
    conn = MagicMock()
    asyncio.run(websocket_api.ws_set_options(
        hass, conn, {"id": 3, "wind_max_delta": 99}))
    assert conn.send_error.call_args.args[1] == "invalid_value"


def test_set_options_empty_entity_clears_key():
    hass, entry = _make_hass()
    entry.options = {"wind_entity": "weather.home", "min_flow_temp": 25.0}
    conn = MagicMock()
    asyncio.run(websocket_api.ws_set_options(
        hass, conn, {"id": 4, "wind_entity": ""}))
    opts = hass.config_entries.async_update_entry.call_args.kwargs["options"]
    assert "wind_entity" not in opts


def test_set_options_min_max_validation():
    hass, _ = _make_hass()
    conn = MagicMock()
    asyncio.run(websocket_api.ws_set_options(
        hass, conn, {"id": 6, "min_flow_temp": 80, "max_flow_temp": 60}))
    assert conn.send_error.call_args.args[1] == "min_flow_above_max"


def test_options_view_in_status():
    hass, entry = _make_hass()
    entry.options = {"curve_coeff": 1.8, "wind_entity": "weather.home"}
    view = websocket_api._options_view(entry.options)
    assert view["curve_coeff"] == 1.8
    assert view["wind_compensation"] is True  # derived: entity picked, flag absent
    assert view["duty_cycle_enabled"] is True  # default
    assert view["rated_heat_input_kw"] == 24.0  # default
