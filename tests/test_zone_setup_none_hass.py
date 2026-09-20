"""Regression: on_trv_update / _trv_state must be safe when hass is None.

crimation_seen: the climate platform crashed during setup with
"'NoneType' object has no attribute 'states'" because wire_zone_sensors()
runs synchronously before entities attach; every room consequently
disappeared right after an option toggle that reloaded the entry.
"""
from unittest.mock import MagicMock

from custom_components.home_climate_control.zone import ZoneClimateEntity


def _bare_zone(trv="climate.office_trv", temp_sensor=None):
    coord = MagicMock()
    coord.curve_coeff = 1.0
    coord.min_flow = 25.0
    coord.max_flow = 75.0
    coord.zones = []
    coord.register_zone = lambda z: None
    z = ZoneClimateEntity.__new__(ZoneClimateEntity)
    ZoneClimateEntity.__init__(z, None, coord, MagicMock(),
                               {"name": "Office", "trv": trv,
                                "temp_sensor": temp_sensor})
    z.hass = None
    return z


def test_trv_state_none_before_attach():
    z = _bare_zone()
    assert z._trv_state() is None


def test_trv_current_temp_none_before_attach():
    z = _bare_zone()
    assert z._trv_current_temp() is None


def test_on_trv_update_noop_before_attach():
    z = _bare_zone()
    z.on_trv_update()  # must not raise; no state write either


def test_refresh_temp_from_trv_noop_before_attach():
    z = _bare_zone()
    z._refresh_temp_from_trv()  # must not raise
    assert z.current_temperature is None
