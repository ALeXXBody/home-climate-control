"""valve_state: display-honest valve state per room.

Rule (2026-11-20 field evidence): the TRV number entity is an opening
*limit*, not a live position — frozen for 24 h across a 15→23 °C house
swing, and reading 59 % beside a stone-cold radiator. Rendering it as a
position told users their valves were stuck open. The panel must show the
live drive state instead; valve-direct rooms are the exception because HCC
writes their opening every tick.
"""
from unittest.mock import MagicMock

from homeassistant.components.climate import HVACMode

from custom_components.home_climate_control.zone import ZoneClimateEntity


def _zone(heat_control="smart", trv=("climate.r_trv",), hvac=HVACMode.HEAT,
          demand=0.0, flow=45.0):
    hass = MagicMock()
    coord = MagicMock()
    coord.curve_coeff = 1.2
    coord.flow_setpoint = flow
    entry = MagicMock()
    entry.entry_id = "e1"
    cfg = {"name": "R", "heat_control": heat_control}
    if trv is None:
        cfg["trv_climates"] = None
    else:
        cfg["trv_climates"] = list(trv)
    z = ZoneClimateEntity(hass, coord, entry, cfg)
    z._hvac_mode = hvac
    z._demand = demand
    return z


def test_valve_state_open_when_calling():
    z = _zone(demand=0.9)
    assert z.hvac_action == "heating"
    assert z.valve_state == "open"


def test_valve_state_closed_when_satisfied():
    z = _zone(demand=0.0)
    assert z.hvac_action == "idle"
    assert z.valve_state == "closed"


def test_valve_state_closed_when_off():
    z = _zone(hvac=HVACMode.OFF, demand=0.9)
    assert z.valve_state == "closed"


def test_valve_state_none_for_manual_room():
    z = _zone(heat_control="manual", trv=None, demand=0.9)
    assert z.valve_state is None


def test_valve_state_none_without_trv():
    z = _zone(trv=None, demand=0.9)
    assert z.valve_state is None


def test_valve_state_valve_direct_follows_drive():
    assert _zone(heat_control="valve", demand=0.5).valve_state == "open"
    assert _zone(heat_control="valve", demand=0.0).valve_state == "closed"
