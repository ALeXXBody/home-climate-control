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


def _controller(balance_autocap, current_val):
    c = CentralController(
        MagicMock(), MagicMock(), curve_coeff=1.0, design_outdoor=-10.0,
        min_flow=25, max_flow=75, balance_autocap=balance_autocap,
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
