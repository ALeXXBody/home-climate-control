"""Secret debug screen feed: home_climate_control/get_debug_log."""

import asyncio
from unittest.mock import MagicMock

from custom_components.home_climate_control import websocket_api
from custom_components.home_climate_control.const import DOMAIN


def _make_hass(controller=None):
    hass = MagicMock()
    hass.data = {DOMAIN: {"e1": {"controller": controller}}}
    return hass


def test_get_debug_log_returns_events_newest_first():
    class Ctrl:
        _debug_log = [
            {"t": "a", "k": "tick", "m": "first"},
            {"t": "2026-09-24T12:00:02", "k": "trv", "m": "Bath Valerie"},
            {"t": "2026-09-24T12:05:00", "k": "boiler", "m": "CH OFF (idle)"},
        ]

    hass = _make_hass(Ctrl())
    conn = MagicMock()
    asyncio.run(websocket_api.ws_get_debug_log(hass, conn, {"id": 1}))
    body = conn.send_result.call_args.args[1]
    assert body["ok"] is True
    # newest first
    assert body["events"][0]["m"] == "CH OFF (idle)"
    assert body["events"][-1]["m"] == "first"


def test_get_debug_log_empty_controller_is_empty_ok():
    hass = _make_hass(None)
    conn = MagicMock()
    asyncio.run(websocket_api.ws_get_debug_log(hass, conn, {"id": 2}))
    body = conn.send_result.call_args.args[1]
    assert body == {"ok": True, "events": []}


def test_controller_debug_log_ring_and_tick_line():
    from custom_components.home_climate_control.central import CentralController

    ctrl = CentralController.__new__(CentralController)
    ctrl._debug_log = []
    for i in range(CentralController.DEBUG_MAX + 25):
        ctrl.debug_log("tick", f"line {i}")
    assert len(ctrl._debug_log) == CentralController.DEBUG_MAX
    assert ctrl._debug_log[-1]["m"] == f"line {CentralController.DEBUG_MAX + 24}"
    assert ctrl._debug_log[0]["m"] == "line 25"  # oldest kept

    ctrl.backend = MagicMock()
    ctrl.backend.outdoor_temp = 11.5
    ctrl.backend.return_temp = None
    ctrl.backend.flame_on = False
    ctrl._ch_on = True
    ctrl.flow_setpoint = 51.0
    ctrl.total_demand = 0.5
    ctrl.active_zone_names = ["Office"]
    ctrl._debug_tick()
    last = ctrl._debug_log[-1]["m"]
    assert "CH on" in last
    assert "flow setpoint 51.0" in last
    assert "return n/a" in last
    assert "Office" in last


def test_zone_trv_push_logs_real_action():
    from unittest.mock import AsyncMock, MagicMock

    from custom_components.home_climate_control.zone import ZoneClimateEntity

    class Coord:
        pass

    coord = Coord()
    coord.debug_log = MagicMock()
    z = object.__new__(ZoneClimateEntity)
    z.coordinator = coord
    z.hass = MagicMock()
    z.hass.services.async_call = AsyncMock()
    z._trv_entity = "climate.office_trv"
    z.heater_control = "smart"
    z._valve_pct = 42.0
    z.effective_setpoint = lambda: 21.0
    z._zone_name = lambda: "Office"

    asyncio.run(z._push_setpoint_to_trv("schedule → comfort"))
    logged = coord.debug_log.call_args
    assert logged.args[0] == "trv"
    assert "Office" in logged.args[1]
    assert "21.0" in logged.args[1]
    assert "valve 42%" in logged.args[1]
    assert "schedule → comfort" in logged.args[1]


def test_zone_valve_move_logs_open_and_close():
    class Coord:
        debug_log = MagicMock()

    coord = Coord()
    from custom_components.home_climate_control.zone import ZoneClimateEntity

    z = object.__new__(ZoneClimateEntity)
    z.coordinator = coord
    z.hass = None
    z.effective_setpoint = lambda: 21.0
    z._current_temp = 20.0
    z._safe_write_ha_state = lambda: None
    z.balance = MagicMock()
    z._balance_samples_to_save = 0
    z._async_persist_balance = None

    z.on_valve_update(10.0)   # first sample → logged as opened
    z.on_valve_update(10.4)   # <1% move → not logged
    z.on_valve_update(75.0)   # big move → logged
    z.on_valve_update(3.0)    # big close → logged
    kinds = [c.args[0] for c in coord.debug_log.call_args_list if c.args]
    assert kinds.count("valve") == 3
