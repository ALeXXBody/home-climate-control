"""Valve-direct close loop: demand → number.set_value writes."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from homeassistant.components.climate import HVACMode
from custom_components.home_climate_control.zone import ZoneClimateEntity
from custom_components.home_climate_control.websocket_api import build_zone_config


async def _noop_sleep(_sec):
    return


def _zone(heat_control="valve", valve_entity="number.office_trv_valve_opening_degree",
          trv="climate.office_trv", demand=0.6, cur_pct=0.0):
    z = object.__new__(ZoneClimateEntity)
    z.heater_control = heat_control
    z._trv_position_entity = valve_entity
    z._trv_entity = trv
    z._trv_climates = [trv]
    z._hvac_mode = HVACMode.HEAT
    z._window_open = False
    z.heater_control = heat_control
    z.demand_level = lambda: demand
    z._valve_last_write = 0.0
    z._valve_pin_at = 0.0
    z._zone_name = lambda: "Office"
    z.effective_setpoint = lambda: 21.0
    z._trv_state = lambda: None
    z._current_temp = 19.0
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.states.get = lambda eid: (
        MagicMock(state=str(cur_pct), attributes={"temperature": 40.0})
        if eid == valve_entity and valve_entity else
        (MagicMock(state="heat", attributes={"temperature": 40.0})
         if eid == trv else None)
    )
    z.hass = hass
    z._hass = hass
    coord = MagicMock()
    coord.debug_log = MagicMock()
    z.coordinator = coord
    return z, hass, coord


def test_valve_active_only_for_number_entities():
    z, _, _ = _zone()
    assert z.valve_direct_active() is True
    z2, _, _ = _zone(valve_entity="sensor.office_trv_valve")
    assert z2.valve_direct_active() is False
    z3, _, _ = _zone(heat_control="smart")
    assert z3.valve_direct_active() is False


def test_build_zone_config_accepts_valve_mode():
    cfg = build_zone_config(
        [], name="Office", heat_control="valve",
        trv_climates=["climate.office_trv"],
        trv_position_entity="number.office_trv_valve_opening_degree",
    )
    assert cfg["heat_control"] == "valve"

    with pytest.raises(ValueError, match="valve position"):
        build_zone_config(
            [], name="Office", heat_control="valve",
            trv_climates=["climate.office_trv"],
        )
    with pytest.raises(ValueError, match="TRV climate"):
        build_zone_config(
            [], name="Office", heat_control="valve",
            trv_position_entity="number.x",
        )


@pytest.mark.asyncio
async def test_valve_apply_writes_proportional_opening():
    z, hass, coord = _zone(demand=0.6, cur_pct=0)
    await asyncio.sleep(0)
    z._valve_last_write = 0.0
    now = 10_000.0
    z.valve_apply(now, hass)  # run inline via patched task? async_create_task is mock
    call = hass.services.async_call.call_args
    assert call is not None
    assert call.args[:2] == ("number", "set_value")
    want = call.args[2]
    assert want["entity_id"] == "number.office_trv_valve_opening_degree"
    assert want["value"] == pytest.approx(70.0)  # demand .6→60% +10 headroom
    assert coord.debug_log.call_args.args[0] == "valve-drive"


@pytest.mark.asyncio
async def test_valve_apply_hysteresis_blocks_minor_moves():
    z, hass, _ = _zone(demand=0.6, cur_pct=68.0)
    z.valve_apply(10_000.0, hass)
    # |70-68| = 2 < 3% hysteresis → no write
    assert hass.services.async_call.await_count == 0


@pytest.mark.asyncio
async def test_valve_apply_window_open_shuts_valve_to_zero():
    z, hass, _ = _zone(demand=0.6, cur_pct=50.0)
    z._window_open = True
    z._valve_last_write = 0.0
    z.valve_apply(3_000.0, hass)
    data = hass.services.async_call.call_args.args[2]
    assert data["value"] == 0.0, "an open window must shut the valve immediately"


@pytest.mark.asyncio
async def test_valve_emit_targets_comfort_setpoint():
    z, hass, _ = _zone(demand=0.0, cur_pct=55.0)
    z._valve_last_write = 0.0
    z.demand_level = lambda: 0.0
    z.valve_apply(2_000.0, hass)
    data = hass.services.async_call.call_args.args[2]
    assert data["value"] == 0.0, "room at target ⇒ valve fully shut"


@pytest.mark.asyncio
async def test_zone_exercise_writes_min_max_restore():
    """Manual/automatic anti-stick sweep: 100 -> 0 -> saved, per room."""
    z, hass, _ = _zone(demand=0.0, cur_pct=55.0)
    z._valve_exercising = False
    z._valve_last_exercise = 0.0
    z._valve_last_write = 0.0
    z.wants_heat = lambda: False  # room idle
    z._exercise_sleep = _noop_sleep
    await z.valve_exercise()
    call_values = [
        c.args[2]["value"]
        for c in hass.services.async_call.await_args_list
        if c.args and c.args[0] == "number"
    ]
    assert call_values == [100.0, 0.0, 55.0]
    assert z._valve_exercising is False
    # Cooldown armed so next tick does nothing for 7 days.
    import time as _t
    assert _t.time() - z._valve_last_exercise < 7 * 86400


def test_push_setpoint_suppresses_noop_within_trv_step():
    """A push whose value is within the TRV own rounding grid is skipped."""
    import asyncio

    from custom_components.home_climate_control.zone import ZoneClimateEntity

    z = object.__new__(ZoneClimateEntity)
    z._trv_entity = "climate.x"
    z.heater_control = "smart"
    z._trv_state = lambda: MagicMock(attributes={"target_temp_step": 1.0,
                                                 "temperature": 21.0})
    _ct = z  # property; skip
    z.effective_setpoint = lambda: 21.2   # inside one grid step of 1.0
    z._zone_name = lambda: "X"
    z._valve_pct = None
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    z._hass = hass
    hass.services.async_call.assert_not_called()


def test_push_setpoint_still_pushes_real_change():
    """A change outside the rounding grid is pushed normally."""
    import asyncio

    from custom_components.home_climate_control.zone import ZoneClimateEntity

    z = object.__new__(ZoneClimateEntity)
    z._trv_entity = "climate.x"
    z.heater_control = "smart"
    z._trv_state = lambda: MagicMock(attributes={"target_temp_step": 1.0,
                                                 "temperature": 20.0})
    z.effective_setpoint = lambda: 21.0
    z._zone_name = lambda: "X"
    z._valve_pct = None
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    z._hass = hass
    z.hass = hass
    asyncio.run(z._push_setpoint_to_trv("test"))
    assert hass.services.async_call.await_count == 1
    data = hass.services.async_call.await_args.args[2]
    assert data["temperature"] == 21.0
