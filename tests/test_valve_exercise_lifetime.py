"""The valve sweep task must die with the room (bound to entity lifetime)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from homeassistant.components.climate import HVACMode
from custom_components.home_climate_control.zone import ZoneClimateEntity


def _zone_idle():
    z = object.__new__(ZoneClimateEntity)
    z.heater_control = "valve"
    z._trv_position_entity = "number.office_trv_valve_opening_degree"
    z._trv_entity = "climate.office_trv"
    z._trv_climates = [z._trv_entity]
    z._hvac_mode = HVACMode.HEAT
    z._window_open = False
    z._current_temp = 20.0
    z._demand = 0.0
    z._valve_last_write = 0.0
    z._valve_exercising = False
    z.demand_level = lambda: 0.0
    z.wants_heat = lambda: False   # idle room (preheat internals not under test)
    z._zone_name = lambda: "Office"
    z.effective_setpoint = lambda: 20.0
    z._trv_state = lambda: None
    z._valve_last_exercise = 0.0
    z._async_persist_balance = AsyncMock()
    hass = MagicMock()
    call_made = []

    def _call(*a, **k):
        # mirror async_create_task: return a real Task we control
        fut = asyncio.get_event_loop().create_future()
        async def _nothing():
            await asyncio.sleep(10000)
        t = asyncio.ensure_future(_nothing())
        call_made.append(t)
        z._valve_exercise_task = t
        return t

    hass.async_create_task = _call
    hass.states.get = lambda eid: MagicMock(state="60", attributes={})
    z.hass = hass
    z._hass = hass
    z.coordinator = MagicMock()
    z.coordinator.debug_log = MagicMock()
    return z, hass, call_made


def test_exercise_task_is_bound_on_the_entity():
    z, hass, tasks = _zone_idle()
    import time as tmod
    z._valve_last_exercise = 0.0
    asyncio.run(z.maybe_exercise(tmod.time()))
    assert len(tasks) == 1
    assert z._valve_exercise_task is tasks[0]
    assert tasks[0] is not None


def test_will_remove_cancels_a_running_sweep():
    z, hass, tasks = _zone_idle()
    import time as tmod
    asyncio.run(z.maybe_exercise(tmod.time()))
    run = tasks[0]
    asyncio.run(z.async_will_remove_from_hass())
    assert run.cancelled()
    assert z._valve_exercise_task is None


def test_new_sweep_supersedes_running_one():
    z, hass, tasks = _zone_idle()
    import time as tmod
    asyncio.run(z.maybe_exercise(tmod.time()))
    first = tasks[0]
    z._valve_last_exercise = 0.0
    asyncio.run(z.maybe_exercise(tmod.time()))
    second = tasks[-1]
    assert first is not second
    assert first.cancelled()
    assert z._valve_exercise_task is second
