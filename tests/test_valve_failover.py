"""Stuck-valve failover: engage / drive / hand-back / re-arm.

Field case: a vendor temperature-source quirk left TRVs holding 0% valves
while rooms demanded heat for days. HCC now takes over the opening directly
and stands down when the TRVs own loop returns.
"""

import time

from unittest.mock import AsyncMock, MagicMock

import pytest

from homeassistant.components.climate import HVACMode
from custom_components.home_climate_control.zone import ZoneClimateEntity


def _zone(heat_control="smart", demand=0.6, cur_pct=0.0,
          trv_action=None, window=False, temp=19.0):
    z = object.__new__(ZoneClimateEntity)
    z.heater_control = heat_control
    z._trv_position_entity = "number.office_trv_valve_opening_degree"
    z._trv_entity = "climate.office_trv"
    z._trv_climates = [z._trv_entity]
    z._hvac_mode = HVACMode.HEAT
    z._window_open = window
    z._current_temp = temp
    z._demand = 0.0
    z._valve_last_write = 0.0
    z._valve_exercising = False
    z.demand_level = lambda: demand
    z._zone_name = lambda: "Office"
    z.effective_setpoint = lambda: 21.0
    z._trv_state = lambda: (
        MagicMock(attributes={"hvac_action": trv_action}) if trv_action
        else None)
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.states.get = lambda eid: (
        MagicMock(state=str(cur_pct), attributes={})
        if eid == z._trv_position_entity else
        (MagicMock(state="heat", attributes={"hvac_action": trv_action})
         if eid == z._trv_entity and trv_action else None))
    z.hass = hass
    z._hass = hass
    z.coordinator = MagicMock()
    z.coordinator.debug_log = MagicMock()
    return z, hass


NOW = time.monotonic()
VALVE_EID = "number.office_trv_valve_opening_degree"


def _failover_fields(prepared, engaged=False):
    z, hass = prepared
    z._valve_failover = engaged
    z._valve_stuck_since = None
    z._valve_failover_rearm_until = 0.0
    z._valve_failover_notified = False
    z._valve_failover_cmd = None
    z._valve_failover_cmd_at = 0.0
    z._valve_failover_idle_since = None
    return z, hass


def test_engage_after_15_min_of_stuck_demand():
    z, hass = _failover_fields(_zone())
    stc = NOW - 901.0
    z._valve_stuck_since = stc
    import asyncio
    asyncio.run(z.valve_failover_tick(NOW, hass))
    assert z.valve_failover_active() is True
    assert hass.services.async_call.await_count >= 1   # notification


def test_no_engage_below_demand_threshold():
    z, hass = _failover_fields(_zone(demand=0.01))
    z._valve_stuck_since = NOW - 3600.0
    import asyncio
    asyncio.run(z.valve_failover_tick(NOW, hass))
    assert z.valve_failover_active() is False


def test_no_engage_with_window_open_or_room_unmeasured():
    z, hass = _failover_fields(_zone(window=True))
    z._valve_stuck_since = NOW - 3600.0
    import asyncio
    asyncio.run(z.valve_failover_tick(NOW, hass))
    assert z.valve_failover_active() is False
    z2, hass2 = _failover_fields(_zone(temp=None))
    z2._valve_stuck_since = NOW - 3600.0
    asyncio.run(z2.valve_failover_tick(NOW, hass2))
    assert z2.valve_failover_active() is False


def test_no_engage_while_trv_reports_heating():
    z, hass = _failover_fields(_zone(cur_pct=0.0, trv_action="heating"))
    z._valve_stuck_since = NOW - 3600.0
    import asyncio
    asyncio.run(z.valve_failover_tick(NOW, hass))
    assert z.valve_failover_active() is False




def test_rearm_blocks_reengage_for_30_min():
    z, hass = _failover_fields(_zone())
    z._valve_failover_rearm_until = NOW + 1800.0
    z._valve_stuck_since = NOW - 3600.0
    import asyncio
    asyncio.run(z.valve_failover_tick(NOW, hass))
    assert z.valve_failover_active() is False


def test_valve_direct_rooms_never_failover():
    z, hass = _failover_fields(_zone(heat_control="valve"))
    assert z.valve_failover_eligible() is False
    z._valve_stuck_since = NOW - 3600.0
    import asyncio
    asyncio.run(z.valve_failover_tick(NOW, hass))
    assert z.valve_failover_active() is False


def test_floor_rooms_never_failover():
    z, hass = _failover_fields(_zone(heat_control="floor"))
    assert z.valve_failover_eligible() is False
    z._valve_stuck_since = NOW - 3600.0
    import asyncio
    asyncio.run(z.valve_failover_tick(NOW, hass))
    assert z.valve_failover_active() is False




def test_no_handback_while_reports_idle():
    z, _ = _failover_fields(_zone(), engaged=True)
    z._valve_failover_cmd = 68.0
    z._valve_failover_cmd_at = NOW - 40.0
    import asyncio
    asyncio.run(z.valve_failover_tick(NOW, z.hass))
    assert z.valve_failover_active() is True


def test_release_when_demand_ends_5_min():
    z, _ = _failover_fields(
        _zone(demand=0.0), engaged=True)
    z._valve_failover_cmd = 68.0
    z._valve_failover_cmd_at = NOW
    z._valve_failover_idle_since = NOW - 301.0
    import asyncio
    asyncio.run(z.valve_failover_tick(NOW, z.hass))
    assert z.valve_failover_active() is False


def test_apply_drives_valve_when_engaged():
    z, hass = _failover_fields(_zone(demand=0.6, cur_pct=0.0), engaged=False)
    z._valve_failover = True
    z.valve_apply(NOW, hass)
    assert hass.services.async_call.call_count >= 1
    args = hass.services.async_call.call_args[0]
    assert args[0] == "number" and args[1] == "set_value"
    assert args[2]["value"] > 0
