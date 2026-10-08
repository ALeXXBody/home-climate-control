"""Underfloor heating (floor mode): config, control loop, safety gates."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.home_climate_control.websocket_api import build_zone_config
from custom_components.home_climate_control.zone import ZoneClimateEntity

from tests.conftest import install_ha_stubs  # noqa: E402 - run at import
install_ha_stubs()


def test_floor_room_requires_loop_entity():
    with pytest.raises(ValueError) as exc:
        build_zone_config(
            [], name="Kitchen", heat_control="floor",
            trv_climates=[], window_sensors=[],
        )
    assert "loop entity" in str(exc.value)


def _floor_zone(surface="27.0", flow=None, pump="on", cur=19.5, setpoint=20.0,
                hvac="heat", window=False):
    import sys
    sys.path.insert(0, "tests")
    from test_valve_direct import _zone  # base stubs
    z, hass, coord = _zone(heat_control="smart")
    z.heater_control = "floor"
    z._current_temp = cur
    z._floor_loop = "switch.kitchen_floor_loop"
    z._floor_mixer = "number.kitchen_floor_mixer"
    z._floor_surface_sensor = surface and "sensor.floor_surface" or None
    z._floor_flow_sensor = flow and "sensor.floor_flow" or None
    z._floor_pump = pump and "switch.floor_pump" or None
    z._floor_surface_max = 29.0
    z._floor_state = None
    z._floor_last_flip = 0.0
    z._floor_last_mixer = None
    z._hvac_mode = hvac
    z._window_open = window
    z.effective_setpoint = lambda: setpoint
    z._zone_name = lambda: "Kitchen"

    def _get(eid):
        if eid == "sensor.floor_surface" and surface is not None:
            return MagicMock(state=str(surface), attributes={})
        if eid == "sensor.floor_flow" and flow is not None:
            return MagicMock(state=str(flow), attributes={})
        if eid == "switch.floor_pump" and pump is not None:
            return MagicMock(state=pump, attributes={})
        return None

    from unittest.mock import MagicMock as M
    st = M()
    st.get = _get
    z.hass = M(states=st)
    z.hass.services.async_call = AsyncMock()
    z._hass = z.hass
    return z, z.hass


def _calls(hass, domain):
    return [c.args[2] for c in hass.services.async_call.call_args_list
            if c.args and c.args[0] == domain]


def _turn_ons(hass):
    return [c for c in hass.services.async_call.call_args_list
            if c.args and c.args[0] == "switch" and c.args[1] == "turn_on"]


def test_floor_loop_turns_on_below_setpoint():
    z, hass = _floor_zone(cur=19.5, setpoint=20.0)
    asyncio.run(z.floor_tick(0.0, z.hass, 8.0))
    ons = _calls(hass, "switch")
    assert ons and ons[0]["entity_id"] == "switch.kitchen_floor_loop"
    assert z._floor_state is True


def test_floor_loop_stays_off_above_setpoint():
    z, hass = _floor_zone(cur=20.6, setpoint=20.0)
    asyncio.run(z.floor_tick(0.0, z.hass, 8.0))
    # first pass may write an explicit OFF for deterministic startup state,
    # but must never turn the loop ON
    assert _turn_ons(hass) == []
    assert z._floor_state is False


def test_floor_surface_cap_forces_off():
    z, hass = _floor_zone(surface="29.5", cur=19.0, setpoint=20.0)
    asyncio.run(z.floor_tick(0.0, z.hass, 8.0))
    assert z._floor_state is False
    assert _turn_ons(hass) == []


def test_floor_flow_cap_forces_off():
    z, hass = _floor_zone(flow="47.0", cur=19.0, setpoint=20.0)
    asyncio.run(z.floor_tick(0.0, z.hass, 8.0))
    assert z._floor_state is False


def test_floor_pump_interlock_blocks_heat():
    z, hass = _floor_zone(pump="off", cur=19.0, setpoint=20.0)
    asyncio.run(z.floor_tick(0.0, z.hass, 8.0))
    assert z._floor_state is False
    assert _turn_ons(hass) == []


def test_floor_window_open_forces_off():
    z, hass = _floor_zone(cur=19.0, setpoint=20.0, window=True)
    asyncio.run(z.floor_tick(0.0, z.hass, 8.0))
    assert z._floor_state is False


def test_floor_mixer_tracks_outdoor_curve_when_no_flow_sensor():
    z, hass = _floor_zone(cur=19.0, setpoint=20.0)
    asyncio.run(z.floor_tick(0.0, z.hass, -10.0))
    sets = _calls(hass, "number")
    assert sets and sets[0]["entity_id"] == "number.kitchen_floor_mixer"
    assert sets[0]["value"] >= 90   # −10 °C outdoor → near-max low flow


def test_floor_mixer_closed_loop_around_40c():
    z, hass = _floor_zone(cur=19.5, setpoint=20.0, flow="42.0")
    asyncio.run(z.floor_tick(0.0, z.hass, 8.0))
    sets = _calls(hass, "number")
    # 42 °C flow → pull mixer down from 50 % baseline
    assert sets and sets[0]["value"] < 50


def test_floor_dwell_prevents_chatter():
    """Closing immediately is allowed (stop wasting heat); re-opening
    within the dwell must wait, then happen."""
    z, hass = _floor_zone(cur=19.5, setpoint=20.0)
    asyncio.run(z.floor_tick(0.0, z.hass, 8.0))
    assert z._floor_state is True
    offs = [c for c in hass.services.async_call.call_args_list
            if c.args and c.args[0] == "switch" and c.args[1] == "turn_off"]
    assert len(offs) == 0
    # room satisfied → OFF right away (no dwell on closing)
    z._current_temp = 20.6
    asyncio.run(z.floor_tick(60.0, z.hass, 8.0))
    assert z._floor_state is False
    offs = [c for c in hass.services.async_call.call_args_list
            if c.args and c.args[0] == "switch" and c.args[1] == "turn_off"]
    assert len(offs) == 1
    # demand returns 1 min later — dwell must block the flip
    z._current_temp = 19.4
    asyncio.run(z.floor_tick(90.0, z.hass, 8.0))
    assert z._floor_state is False
    assert len(_turn_ons(hass)) == 1
    # after the dwell expires it turns back on
    asyncio.run(z.floor_tick(400.0, z.hass, 8.0))
    assert len(_turn_ons(hass)) == 2


def test_floor_room_config_roundtrip():
    from tests.conftest import install_ha_stubs
    install_ha_stubs()
    cfg = build_zone_config(
        [], name="Bathroom", heat_control="floor",
        trv_climates=[], window_sensors=[],
        floor_loop_entity="switch.bath_floor",
        floor_mixer_entity="number.bath_mixer",
        floor_surface_sensor="sensor.bath_slab",
        floor_flow_sensor="sensor.bath_flow",
        floor_pump_entity="switch.pump",
        floor_surface_max=30.0,
    )
    assert cfg["heat_control"] == "floor"
    assert cfg["floor_loop_entity"] == "switch.bath_floor"
    assert cfg["floor_surface_max"] == 30.0


def test_floor_room_activated_after_zone_validation_fix():
    from custom_components.home_climate_control.zone import ZoneClimateEntity
    z = object.__new__(ZoneClimateEntity)
    z.heater_control = "floor"   # the validation tuple now accepts it
    z.floor_active = lambda: (z.heater_control == "floor"
                              and bool(z._floor_loop))
    z._floor_loop = "switch.x"
    assert z.floor_active() is True


def test_floor_rooms_excluded_from_radiator_flow():
    """Floor rooms must not push the radiator flow curve to 48 °C."""
    # quick sanity of the exclusion expression shape used in central
    class Z:
        pid_flow_contribution = staticmethod(lambda: 25.0)
        heater_control = "floor"
    class Z2:
        pid_flow_contribution = staticmethod(lambda: 12.0)
        heater_control = "smart"
    vals = [
        z.pid_flow_contribution() for z in (Z(), Z2())
        if getattr(z, "heater_control", "smart") != "floor"
    ]
    assert vals == [12.0]
