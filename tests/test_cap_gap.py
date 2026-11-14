"""Learned-ceiling gap alarm + one-click re-test.

2026-11-14 field evidence: the curve wanted ~72 °C while the board received
55.00 on every write for days (boiler bound 80). The hub clamped to the cap
and the board's probe could never test above it. The watcher below is the
alarm that would have fired on day one; the re-test button is the fix.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from custom_components.home_climate_control.central import CentralController
from custom_components.home_climate_control.const import DOMAIN


def _controller(cap=55.0):
    c = CentralController(
        MagicMock(), MagicMock(), curve_coeff=3.0, design_outdoor=-10.0,
        min_flow=25, max_flow=75,
    )
    c.hass = MagicMock()
    c.hass.data = {DOMAIN: {}}
    c.backend.connected = True
    c.backend.ot_valid = True
    c.backend.tset_cap = cap
    c._ch_on = True
    return c


def test_gap_alarm_raises_after_sustained_gap():
    c = _controller()
    for _ in range(29):
        c._maybe_cap_gap_tick(72.0)
        assert not c._cap_gap_active
    c._maybe_cap_gap_tick(72.0)
    assert c._cap_gap_active
    assert c._cap_gap_info["want_c"] == 72.0
    assert c._cap_gap_info["cap_c"] == 55.0


def test_gap_no_alarm_when_small_or_off_or_unknown():
    c = _controller()  # gap 2 < 5: counts nothing
    for _ in range(40):
        c._maybe_cap_gap_tick(57.0)
    assert not c._cap_gap_active
    assert c._cap_gap_ticks == 0

    c = _controller(cap=None)  # no ceiling learned: nothing to alarm on
    for _ in range(40):
        c._maybe_cap_gap_tick(72.0)
    assert not c._cap_gap_active

    c = _controller()  # burner off: gap is meaningless
    c._ch_on = False
    for _ in range(40):
        c._maybe_cap_gap_tick(72.0)
    assert not c._cap_gap_active


def test_gap_resets_in_deadband_and_dismisses():
    c = _controller()
    for _ in range(30):
        c._maybe_cap_gap_tick(72.0)
    assert c._cap_gap_active
    c._maybe_cap_gap_tick(60.0)  # gap 5 still counts
    assert c._cap_gap_active
    c._maybe_cap_gap_tick(56.0)  # gap 1 < hysteresis 2 → healed
    assert not c._cap_gap_active
    assert c._cap_gap_ticks == 0


def test_backend_publishes_clear_cap_command():
    from homeassistant.components import mqtt

    from custom_components.home_climate_control.boiler.hcs_mqtt import (
        HcsMqttBackend,
    )

    b = HcsMqttBackend(MagicMock(), "hcs-a", min_flow=25, max_flow=75)
    asyncio.run(b.async_clear_tset_cap())
    topic, payload = mqtt.async_publish.call_args[0][1:3]
    assert topic == "hcs/hcs-a/set/clear_tset_cap"
    assert payload == "clear"


def _ws_hass(controller):
    hass = MagicMock()
    hass.data = {DOMAIN: {"e1": {"controller": controller}}}
    hass.config_entries.async_get_entry = lambda eid: SimpleNamespace(
        entry_id=eid)
    return hass


def test_ws_retest_calls_board_and_resets_watch():
    from custom_components.home_climate_control import websocket_api as ws

    backend = MagicMock()
    backend.tset_cap = 55.0
    backend.async_clear_tset_cap = AsyncMock()
    controller = SimpleNamespace(backend=backend, _cap_gap_ticks=30)
    hass = _ws_hass(controller)
    conn = MagicMock()
    asyncio.run(ws.ws_retest_tset_cap(
        hass, conn, {"id": 1, "type": "home_climate_control/retest_tset_cap"}))
    backend.async_clear_tset_cap.assert_awaited_once()
    assert controller._cap_gap_ticks == 0
    assert conn.send_result.called


def test_ws_retest_rejected_without_linked_board():
    from custom_components.home_climate_control import websocket_api as ws

    controller = SimpleNamespace(backend=SimpleNamespace())  # demo: no cap
    hass = _ws_hass(controller)
    conn = MagicMock()
    asyncio.run(ws.ws_retest_tset_cap(
        hass, conn, {"id": 1, "type": "home_climate_control/retest_tset_cap"}))
    assert conn.send_error.called
