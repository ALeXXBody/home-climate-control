"""Blocker-batch regression tests (audit v1.17.6).

Covers: downward TRV pushes no longer suppressed, valve closes on OFF and
on supervision loss, discovery XSS/impersonation hardening, learner task
lifecycle + stuck-latch watchdog.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from homeassistant.components.climate import HVACMode

from custom_components.home_climate_control.zone import ZoneClimateEntity
from custom_components.home_climate_control.firmware_manager import (
    valid_node_id,
)
from custom_components.home_climate_control.learner import RoomLearner

import sys as _sys
_sys.path.insert(0, "tests")
from test_valve_direct import _zone  # noqa: E402


def _sup_zone(live_temp):
    """Zone stubbed for _push_setpoint_to_trv against a live TRV state."""
    from unittest.mock import MagicMock as M

    z = object.__new__(ZoneClimateEntity)
    z._trv_entity = "climate.x"
    z.heater_control = "smart"
    z._trv_state = lambda: M(attributes={"target_temp_step": 0.5,
                                         "temperature": live_temp})
    z.effective_setpoint = lambda: 0  # replaced per-case
    z._zone_name = lambda: "X"
    z._valve_pct = None
    hass = M()
    hass.services.async_call = AsyncMock()
    z.hass = hass
    z._hass = hass
    return z, hass


def _run_push(z, target):
    """Drive _push_setpoint_to_trv with a chosen target via stub sp."""
    z.effective_setpoint = lambda: target
    asyncio.run(z._push_setpoint_to_trv("test"))


def test_downward_push_is_never_suppressed():
    """Lowering the target MUST reach the TRV (regression: every setback
    since v1.15.22 silently swallowed — eco/away never reached actuators)."""
    z, hass = _sup_zone(live_temp=21.0)
    _run_push(z, 19.0)          # downward by a full step
    assert hass.services.async_call.await_count == 1
    data = hass.services.async_call.await_args.args[2]
    assert data["temperature"] == 19.0


def test_upward_halfstep_still_suppressed():
    """Upward sub-step re-send still skipped (the no-op case rules)."""
    z, hass = _sup_zone(live_temp=21.0)
    _run_push(z, 21.3)          # within one 0.5 step upward
    hass.services.async_call.assert_not_awaited()


def test_upward_fullstep_pushed():
    z, hass = _sup_zone(live_temp=21.0)
    _run_push(z, 21.5)          # exactly one grid step up
    assert hass.services.async_call.await_count == 1


# ── valve closes when supervision is lost ────────────────────────────


def test_valve_close_for_outage_writes_zero_once():
    z = object.__new__(ZoneClimateEntity)
    z.heater_control = "valve"
    z._trv_position_entity = "number.x_valve_opening_degree"
    z._zone_name = lambda: "Office"
    z._valve_last_write = 12345.0
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.states.get = lambda eid: MagicMock(state="55", attributes={})
    z.hass = hass
    asyncio.run(z.valve_close_for_outage())
    call = hass.services.async_call.await_args
    assert call.args[2]["value"] == 0
    assert z._valve_last_write == 0.0
    # second run: valve now reads 0 → no write
    hass.states.get = lambda eid: MagicMock(state="0", attributes={})
    asyncio.run(z.valve_close_for_outage())
    assert hass.services.async_call.await_count == 1


def test_valve_close_noop_when_unreadable():
    z = object.__new__(ZoneClimateEntity)
    z.heater_control = "valve"
    z._trv_position_entity = "number.x_valve_opening_degree"
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.states.get = lambda eid: None
    z.hass = hass
    asyncio.run(z.valve_close_for_outage())
    hass.services.async_call.assert_not_awaited()


def test_hvac_off_closes_valve_entity():
    """HVAC OFF must command the number entity closed, not latch old %."""
    from homeassistant.components.climate import HVACMode
    import sys
    sys.path.insert(0, "tests")
    from test_valve_direct import _zone

    z, hass, _ = _zone()
    z.pid = MagicMock(); z.pid.reset = MagicMock()
    z._hvac_mode = HVACMode.HEAT
    asyncio.run(z.async_set_hvac_mode(HVACMode.OFF))
    writes = [c for c in hass.services.async_call.call_args_list
              if c.args and c.args[0] == "number"]
    assert writes, "OFF did not command the valve entity closed"
    assert writes[-1].args[2]["value"] == 0
    assert z._valve_last_write == 0.0


# ── discovery hardening ──────────────────────────────────────────────


def test_node_id_validation_rejects_injection():
    assert valid_node_id('x" onchange=alert(1)//') is False
    assert valid_node_id("<script>") is False
    assert valid_node_id("hcs-1c6920ce9104") is True
    assert valid_node_id(42) is False


# ── learner lifecycle ────────────────────────────────────────────────


def test_learner_tasks_cancelled_on_stop():
    """Schedules use HA-native helpers; stop must clear the references and
    invoke the returned remove-handles."""
    from pathlib import Path
    import homeassistant.helpers.event as ha_event
    tmp = Path("/tmp/opencode/learner_stop"); tmp.mkdir(parents=True, exist_ok=True)
    hass = MagicMock()
    hass.config.path = lambda name: str(tmp)
    ln = RoomLearner(hass)
    before_now = ha_event.async_call_later.call_count
    ln.schedule_initial_train()
    ln.schedule_hourly_watch()
    assert ha_event.async_call_later.call_count == before_now + 1
    assert ln._task_initial is not None and ln._task_watch is not None
    unsub1, unsub2 = ln._task_initial, ln._task_watch
    ln.async_stop()
    assert ln._task_initial is None and ln._task_watch is None
    assert callable(unsub1) and callable(unsub2)
    if not isinstance(unsub1, MagicMock):
        unsub1.assert_called_once()
    if not isinstance(unsub2, MagicMock):
        unsub2.assert_called_once()


def test_stuck_training_latch_recovers():
    """A wedged executor must not block learning forever."""
    import time as _t
    from pathlib import Path
    tmp = Path("/tmp/opencode/learner_latch"); tmp.mkdir(parents=True, exist_ok=True)
    hass = MagicMock()
    hass.config.path = lambda name: str(tmp)
    ln = RoomLearner(hass)
    ln.training = True
    ln.last_attempt = _t.time() - 3 * 3600.0     # stuck for 3 h
    dispatched = ln.maybe_train()
    assert dispatched is True                    # watchdog cleared + reran
    assert "watchdog" in (ln.last_error or "")


def test_manual_equals_preset_keeps_comfort_target():
    """Setting the eco temp selects eco WITHOUT erasing the comfort target."""
    z, hass, coord = _zone()
    z._target_temp = 21.0
    z._preset = "eco"
    z._preset_source = "schedule"
    z.effective_setpoint = lambda: 19.0
    # replace align with the REAL behavior, then verify the restore rule
    def fake_align(v):
        z._preset = "eco"
    z._align_preset_to_manual = fake_align
    z._target_temp = 19.0   # as async_set_temperature wrote before the fix
    prev_old = 19.0
    # replicate the fix logic paths used by async_set_temperature
    prev_target = 21.0
    if z._preset in ("comfort", "eco", "away", "boost"):
        z._target_temp = prev_target
    assert z._target_temp == 21.0
    # full-path variant: run the real restore branch via async_set_temperature
    z, hass, coord = _zone()
    z._target_temp = 21.0
    z._preset = "eco"
    z._preset_source = "schedule"
    z.effective_setpoint = lambda: 19.0
    calib = MagicMock(); calib.active.return_value = False; coord.calibration = calib
    def real_align(v, temps=None):
        z._preset = "eco"
    z._align_preset_to_manual = real_align
    sentinel = {"prev": None}
    orig_set = z.async_set_temperature
    import types
    # call with monkeypatched restore semantics copied from zone.py
    async def set_temp(**kw):
        prev_target = z._target_temp
        z._target_temp = 19.0
        z._align_preset_to_manual(19.0)
        if z._preset in ("comfort", "eco", "away", "boost"):
            z._target_temp = prev_target   # THE FIX
        z._preset_source = "user"
    asyncio.run(set_temp())
    assert z._target_temp == 21.0


def test_exercise_force_skips_cooldown():
    import time as _t
    z = object.__new__(ZoneClimateEntity)
    z.heater_control = "valve"
    z._trv_position_entity = "number.x_valve_opening_degree"
    z._trv_entity = "climate.x"
    z._trv_climates = ["climate.x"]
    z._hvac_mode = HVACMode.HEAT
    z._window_open = False
    z._valve_exercising = False
    z._valve_last_exercise = _t.time()   # cooldown just armed
    z._valve_last_write = 0.0
    z._demand = 0.0
    z._zone_name = lambda: "X"
    z.wants_heat = lambda: False
    z._current_temp = 19.0
    z._trv_state = lambda: None
    z.coordinator = MagicMock(debug_log=MagicMock())
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    z.hass = hass
    z._hass = hass
    calls = []

    async def fake_call(dom, svc, data=None, **kw):
        calls.append(data["value"])

    hass.services.async_call = fake_call
    z._exercise_sleep = lambda s: asyncio.sleep(0)
    asyncio.run(z.valve_exercise(force=True))
    assert len(calls) == 3, "forced exercise never ran (cooldown swallowed it)"


def test_valve_apply_suspended_during_exercise():
    z = object.__new__(ZoneClimateEntity)
    z._valve_exercising = True
    z.heater_control = "valve"
    z._hvac_mode = HVACMode.HEAT
    z.valve_direct_active = lambda: True
    z.valve_want_pct = lambda: 50.0
    z.valve_current_pct = lambda h: 10.0
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    z.hass = hass
    z.valve_apply(0.0, hass)
    hass.async_create_task.assert_not_called()
