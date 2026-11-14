"""Training rows carry supply-side truth (valve + cap per zone).

2026-11-14: the corpus recorded symptoms (cold rooms, high demand) but not
the cause — LivingRoom's 31 % actuator cap and the 55 °C flow ceiling were
invisible to any model trained on it. These tests pin the two columns that
close that blindness.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

from custom_components.home_climate_control.central import CentralController


def _zone(valve_pct=31.0, cap_entity="number.livingroom_trv_valve_opening_degree"):
    z = SimpleNamespace(
        name="LivingRoom",
        floor=0,
        heater_control="smart",
        current_temperature=20.1,
        _target_temp=23.0,
        _valve_pct=valve_pct,
        _preset="none",
        _preheat_active=False,
        _trv_position_entity=cap_entity,
        demand_level=lambda: 0.97,
        wants_heat=lambda: True,
        paused=lambda: False,
        hvac_action="heating",
        effective_setpoint=lambda: 23.0,
        lead_time_s=None,
        radiator_kw=None,
    )
    return z


def _controller(zones, cap_state="31"):
    c = CentralController(
        MagicMock(), MagicMock(), curve_coeff=3.0, design_outdoor=-10.0,
        min_flow=25, max_flow=75,
    )
    c.hass = MagicMock()
    s = MagicMock()
    s.state = cap_state
    c.hass.states.get = lambda ent: s if str(ent).startswith("number.") else None
    c.backend = MagicMock()
    c.backend.flame_on = True
    c.backend.modulation_level = 12.0
    c.backend.return_temp = 46.6
    c.backend.flow_temp = 55.1
    c._ch_on = True
    c.flow_setpoint = 55.0
    c.outdoor_temp = lambda: -1.2
    c.health = MagicMock()
    c.health.flag_for = lambda name: None
    c.zones = zones
    c.setbacks = None
    c.deadtime = None
    c.insulation = None
    return c


def test_training_row_carries_valve_and_cap():
    c = _controller([_zone()])
    row = c._training_row()
    zr = next(z for z in row["zones"] if z["name"] == "LivingRoom")
    assert zr["valve_pct"] == 31.0
    assert zr["valve_cap_pct"] == 31.0


def test_training_row_cap_none_without_entity():
    c = _controller([_zone(valve_pct=100.0, cap_entity=None)])
    row = c._training_row()
    zr = row["zones"][0]
    assert zr["valve_pct"] == 100.0
    assert zr["valve_cap_pct"] is None
