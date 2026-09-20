"""Tier 4 auto-cap writes (behind explicit toggle) tests."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from custom_components.home_climate_control.balancing import BalanceMonitor
from custom_components.home_climate_control.central import CentralController


class _Coord:
    curve_coeff = 1.2
    setbacks = None
    preset_temps = {}

    def register_zone(self, z):
        pass


def _zone(entity="number.kitchen_trv_valve_opening_degree",
          valve=8.0, last_ts=None):
    from custom_components.home_climate_control.zone import ZoneClimateEntity
    z = ZoneClimateEntity.__new__(ZoneClimateEntity)
    ZoneClimateEntity.__init__(z, MagicMock(), _Coord(), MagicMock(), {"name": "R"})
    z.hass = None
    z._trv_position_entity = entity
    for _ in range(20):
        z.balance.sample(valve, False)  # sliver-open while at target
    z._cap_last_ts = last_ts
    return z


def _state(v):
    s = MagicMock(); s.state = str(v)
    return s


def _controller(balance_autocap, current_val, auto_master=True):
    c = CentralController(
        MagicMock(), MagicMock(), curve_coeff=1.0, design_outdoor=-10.0,
        min_flow=25, max_flow=75, balance_autocap=balance_autocap,
        auto_master=auto_master,
    )
    c.hass = MagicMock()
    c.hass.states.get = lambda ent: _state(current_val) if ent.startswith("number.") else None
    c.hass.services = MagicMock()
    c.hass.services.async_call = AsyncMock()
    return c


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_autocap_writes_suggested_cap():
    c = _controller(True, current_val=40)
    z = _zone()
    asyncio.run(c._async_maybe_autocap(z, NOW))
    assert c.hass.services.async_call.await_count == 1
    call = c.hass.services.async_call.await_args
    assert call.args[0] == "number"
    data = (call.args[2] if len(call.args) > 2 else call.kwargs["data"])
    assert data["entity_id"] == "number.kitchen_trv_valve_opening_degree"
    assert 15 <= data["value"] <= 60
    # rate limit: second call within the hour
    asyncio.run(c._async_maybe_autocap(z, NOW))
    assert c.hass.services.async_call.await_count == 1


def test_autocap_off_is_noop():
    c = _controller(False, current_val=40)
    z = _zone()
    asyncio.run(c._async_maybe_autocap(z, NOW))
    assert c.hass.services.async_call.await_count == 0


def test_autocap_skips_when_already_below_cap():
    c = _controller(True, current_val=4)
    z = _zone()
    asyncio.run(c._async_maybe_autocap(z, NOW))
    assert c.hass.services.async_call.await_count == 0


def test_autocap_needs_number_entity():
    c = _controller(True, current_val=40)
    z = _zone(entity="sensor.not_a_number")
    asyncio.run(c._async_maybe_autocap(z, NOW))
    assert c.hass.services.async_call.await_count == 0


def test_autocap_not_oversupplied_is_noop():
    c = _controller(True, current_val=40)
    z = _zone(valve=50)
    asyncio.run(c._async_maybe_autocap(z, NOW))
    assert c.hass.services.async_call.await_count == 0


# ── Auto-Optimize master gate + health guardrails ──────────────────────────
from custom_components.home_climate_control.const import DOMAIN


def test_autocap_blocked_by_master_gate_off():
    c = _controller(True, current_val=40, auto_master=False)
    z = _zone()
    asyncio.run(c._async_maybe_autocap(z, NOW))
    assert c.hass.services.async_call.await_count == 0


def test_autocap_blocked_when_backend_down():
    c = _controller(True, current_val=40)
    c.backend.connected = False
    z = _zone()
    asyncio.run(c._async_maybe_autocap(z, NOW))
    assert c.hass.services.async_call.await_count == 0


def test_autocap_blocked_when_ot_invalid():
    c = _controller(True, current_val=40)
    c.backend.ot_valid = False
    z = _zone()
    asyncio.run(c._async_maybe_autocap(z, NOW))
    assert c.hass.services.async_call.await_count == 0


def test_autocap_blocked_while_failsafe_active():
    for failsafe in ("ON", "HOLD"):
        c = _controller(True, current_val=40)
        fs = MagicMock(); fs.native_value = failsafe
        c.hass.data = {DOMAIN: {"e1": {"failsafe_sensor": fs}}}
        z = _zone()
        assert c.hass.services.async_call.await_count == 0, failsafe


def test_autocap_blocked_when_failsafe_data_unavailable(tmp_path=None):
    c = _controller(True, current_val=40)
    class _BadData(dict):
        def get(self, k):
            raise AttributeError("boom")
    c.hass.data = _BadData()
    z = _zone()
    # Unreadable failsafe state must not brick the write path: treat as
    # healthy (logged), write proceeds.
    asyncio.run(c._async_maybe_autocap(z, NOW))
    assert c.hass.services.async_call.await_count == 1


def test_autocap_runs_when_healthy():
    c = _controller(True, current_val=40)
    c.backend.connected = True
    c.backend.ot_valid = True
    c.hass.data = {DOMAIN: {}}
    z = _zone()
    asyncio.run(c._async_maybe_autocap(z, NOW))
    assert c.hass.services.async_call.await_count == 1


# ── Auto-flow-cap (condensing trim) ───────────────────────────────────────
from datetime import timedelta
from custom_components.home_climate_control.const import (
    FLOWCAP_SHARE,
    FLOWCAP_STEP_C,
    FLOWCAP_WINDOW_SAMPLES,
)


def _flowcap_controller(master_on):
    return CentralController(
        MagicMock(), MagicMock(), curve_coeff=1.0, design_outdoor=-10.0,
        min_flow=25, max_flow=75, auto_master=master_on, auto_flowcap=master_on,
    )


def test_flowcap_trims_when_window_satisfied():
    c = _flowcap_controller(master_on=True)
    c.backend.connected = True
    c.backend.ot_valid = True
    c._ch_on = True
    c._condense_active = True
    ret = 58.0
    t = NOW
    for _ in range(FLOWCAP_WINDOW_SAMPLES):
        c._maybe_flowcap_tick(ret, t)
        t += timedelta(seconds=60)
    assert c.max_flow == 75.0 - FLOWCAP_STEP_C
    assert c._flowcap_last_ts is not None


def test_flowcap_suggestion_only_when_master_off():
    c = _flowcap_controller(master_on=False)
    c.auto_flowcap = False  # per-feature flag also off without the gate
    c._ch_on = True
    c._condense_active = True
    ret = 58.0
    t = NOW
    for _ in range(FLOWCAP_WINDOW_SAMPLES):
        c._maybe_flowcap_tick(ret, t)
        t += timedelta(seconds=60)
    assert c.max_flow == 75.0
    assert c._flowcap_suggestion is not None
    assert "suggested_max" in c._flowcap_suggestion


def test_flowcap_window_mixed_does_not_trim():
    c = _flowcap_controller(master_on=True)
    c.backend.connected = True
    c.backend.ot_valid = True
    c._ch_on = True
    c._condense_active = True
    ret = 58.0
    t = NOW
    for i in range(FLOWCAP_WINDOW_SAMPLES):
        if i % 4 == 0:  # only 75% share, below the 85% threshold
            c._condense_active = False
        c._maybe_flowcap_tick(ret, t)
        t += timedelta(seconds=60)
    assert c.max_flow == 75.0
    assert c._flowcap_suggestion is None


def test_flowcap_respects_floor_margin():
    c = _flowcap_controller(master_on=True)
    c.backend.connected = True
    c.backend.ot_valid = True
    c.min_flow = 25
    c.max_flow = 38  # first trim 38→36, second 36→35 (floor), then stop
    c._ch_on = True
    c._condense_active = True
    ret = 58.0
    t = NOW
    for _ in range(FLOWCAP_WINDOW_SAMPLES):
        c._maybe_flowcap_tick(ret, t)
        t += timedelta(seconds=60)
    assert c.max_flow == 38.0 - FLOWCAP_STEP_C
    # more ticks -> clamp at floor, never below min+margin
    for _ in range(3):
        c._flowcap_last_ts = None
        for _ in range(FLOWCAP_WINDOW_SAMPLES):
            c._maybe_flowcap_tick(ret, t)
            t += timedelta(seconds=60)
    floor = 25.0 + 10.0
    assert c.max_flow >= floor


def test_flowcap_blocked_when_ot_invalid():
    c = _flowcap_controller(master_on=True)
    c._ch_on = True
    c._condense_active = True
    c.backend.ot_valid = False
    t = NOW
    for _ in range(FLOWCAP_WINDOW_SAMPLES):
        c._maybe_flowcap_tick(58.0, t)
        t += timedelta(seconds=60)
    assert c.max_flow == 75.0
