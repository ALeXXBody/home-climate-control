"""Blocker-batch regression tests (audit v1.17.6).

Covers: downward TRV pushes no longer suppressed, valve closes on OFF and
on supervision loss, discovery XSS/impersonation hardening, learner task
lifecycle + stuck-latch watchdog.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.home_climate_control.zone import ZoneClimateEntity
from custom_components.home_climate_control.firmware_manager import (
    valid_node_id,
)
from custom_components.home_climate_control.learner import RoomLearner


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
    from pathlib import Path
    tmp = Path("/tmp/opencode/learner_stop"); tmp.mkdir(parents=True, exist_ok=True)
    hass = MagicMock()
    hass.config.path = lambda name: str(tmp)
    ln = RoomLearner(hass)
    ln.schedule_initial_train()
    ln.schedule_hourly_watch()
    i_t, w_t = ln._task_initial, ln._task_watch
    assert i_t is not None and w_t is not None
    ln.async_stop()
    assert i_t.cancel.call_count >= 1
    assert w_t.cancel.call_count >= 1
    assert ln._task_initial is None and ln._task_watch is None


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
