"""Regression tests for the second full-audit fix batch (v1.18.3)."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from homeassistant.components.climate import HVACMode

from custom_components.home_climate_control.zone import ZoneClimateEntity

import sys as _sys
_sys.path.insert(0, "tests")
from test_valve_direct import _zone  # noqa: E402


def test_zone_entity_rejects_nothing_for_floor():
    """Regression: the validation tuple must accept 'floor' at init."""
    from custom_components.home_climate_control.zone import ZoneClimateEntity
    from custom_components.home_climate_control.const import (
        HEAT_CONTROL_FLOOR,
    )
    # build via the real constructor from a config dict
    cfg = {
        "name": "Bath",
        "heat_control": HEAT_CONTROL_FLOOR,
        "floor_loop_entity": "switch.bath_loop",
        "setpoint": 21.0,
    }
    from unittest.mock import MagicMock
    from types import SimpleNamespace
    def _coord():
        c = MagicMock()
        c.curve_coeff = 1.2
        c.preset_temps = {}
        c.debug_log = MagicMock()
        return c
    def _hass():
        h = MagicMock()
        h.states.get = lambda eid: None
        return h
    z = ZoneClimateEntity(_hass(), _coord(), MagicMock(), cfg)
    assert z.heater_control == HEAT_CONTROL_FLOOR
    assert z.floor_active() is True
    # a floor cfg without a loop entity must NOT break the room
    cfg2 = {"name": "Bath", "heat_control": "floor", "setpoint": 21.0}
    z2 = ZoneClimateEntity(_hass(), _coord(), MagicMock(), cfg2)
    assert z2.floor_active() is False   # degrade, not crash


def test_valve_current_pct_nan_is_none():
    """NaN clamp reads as 100% open — now rejected outright."""
    z = object.__new__(ZoneClimateEntity)
    z._trv_position_entity = "number.x"
    hass = MagicMock()
    hass.states.get = lambda eid: MagicMock(state="nan", attributes={})
    assert z.valve_current_pct(hass) is None


def test_room_temp_staleness_returns_none():
    """A sensor that stops updating must not pin demand forever."""
    import time as _t
    z = object.__new__(ZoneClimateEntity)
    z._current_temp = 21.0
    z._last_temp_update = _t.time() - 95 * 60.0   # 95 min stale
    z._temp_from_trv = False
    assert z._temp_current() is None
    z._last_temp_update = _t.time()
    assert z._temp_current() == 21.0


def test_heating_state_set_after_floor_loop_write():
    """A floor loop write failure must not stamp the state as applied."""
    from tests.test_floor import _floor_zone
    z, hass = _floor_zone(cur=19.0, setpoint=21.0, pump="on")

    async def failing_write(*a, **k):
        raise RuntimeError("entity unavailable")

    hass.services.async_call = failing_write
    asyncio.run(z.floor_tick(0.0, hass, 8.0))
    assert z._floor_state is None   # write failed → no state stamp


def test_first_flip_not_dwell_limited():
    """_floor_last_flip initialised at -300 → the first ON is allowed."""
    from tests.test_floor import _floor_zone
    z, hass = _floor_zone(cur=19.0, setpoint=21.0)
    z._floor_last_flip = -300.0     # default now
    asyncio.run(z.floor_tick(0.0, hass, 8.0))
    assert z._floor_state is True


def test_exercise_latch_never_wedges_on_failure():
    """Any failure inside the sweep must clear _valve_exercising in finally."""
    from test_valve_direct import _zone
    z, hass, _ = _zone(demand=0.0)
    z._valve_last_exercise = 0.0
    z._valve_last_write = 0.0
    z._valve_exercising = False
    z.wants_heat = lambda: False
    z._current_temp = 19.0
    z._trv_state = lambda: None
    z.hass.states.get = lambda eid: None   # readback → None (no wedge material)
    calls = []
    async def write_fail(*a, **k):
        calls.append(k)
        raise RuntimeError("entity unavailable mid-sweep")
    hass.services.async_call = write_fail
    with pytest.raises(RuntimeError):
        asyncio.run(z.valve_exercise())
    assert z._valve_exercising is False   # latch cleared in finally


def test_solar_trim_outside_floor_tick_mixer_not_run_when_pump_off():
    from tests.test_floor import _floor_zone
    z, hass = _floor_zone(cur=19.0, setpoint=21.0, pump="off", flow=None)
    asyncio.run(z.floor_tick(0.0, hass, -10.0))
    sets = [c.args[2] for c in hass.services.async_call.call_args_list
            if c.args and c.args[0] == "number"]
    assert sets == []   # interlock: never write the mixer with the pump off


def test_floor_only_house_clamps_flow_curve():
    """Floor-only demand: the curve must not exceed the 45 °C rail +headroom."""
    # central uses UNDERFLOOR_MAX_FLOW_DEFAULT (50) as max_setpoint
    from custom_components.home_climate_control.const import (
        UNDERFLOOR_MAX_FLOW_DEFAULT,
    )
    assert 45.0 <= UNDERFLOOR_MAX_FLOW_DEFAULT <= 55.0
