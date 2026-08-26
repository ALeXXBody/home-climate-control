"""Outdoor temp source priority: boiler → HA sensor → stale boiler → None."""

from unittest.mock import MagicMock

from custom_components.home_climate_control.central import CentralController
from tests.test_controller import FakeBackend


def _ctrl(backend=None, outdoor_sensor=None, stale_s=1800.0):
    hass = MagicMock()
    be = backend or FakeBackend()
    return CentralController(
        hass,
        be,
        curve_coeff=1.2,
        design_outdoor=-10,
        min_flow=25,
        max_flow=75,
        outdoor_sensor=outdoor_sensor,
        outdoor_stale_s=stale_s,
    ), hass, be


def test_boiler_preferred_when_fresh():
    ctrl, hass, be = _ctrl(outdoor_sensor="sensor.out")
    be._outdoor = 3.0
    # FakeBackend has no outdoor_age_s → treated as fresh
    assert ctrl.outdoor_temp() == 3.0
    assert ctrl.outdoor_source == "boiler"


def test_ha_used_when_boiler_missing():
    ctrl, hass, be = _ctrl(outdoor_sensor="sensor.out")
    be._outdoor = None
    st = MagicMock()
    st.state = "7.5"
    hass.states.get.return_value = st
    assert ctrl.outdoor_temp() == 7.5
    assert ctrl.outdoor_source == "ha"
    hass.states.get.assert_called_with("sensor.out")


def test_ha_used_when_boiler_stale():
    class Aged(FakeBackend):
        @property
        def outdoor_age_s(self):
            return 5000.0  # > 1800

    be = Aged()
    be._outdoor = -2.0
    ctrl, hass, _ = _ctrl(backend=be, outdoor_sensor="sensor.out", stale_s=1800)
    st = MagicMock()
    st.state = "4.0"
    hass.states.get.return_value = st
    assert ctrl.outdoor_temp() == 4.0
    assert ctrl.outdoor_source == "ha"


def test_stale_boiler_when_no_ha():
    class Aged(FakeBackend):
        @property
        def outdoor_age_s(self):
            return 9000.0

    be = Aged()
    be._outdoor = -1.0
    ctrl, hass, _ = _ctrl(backend=be, outdoor_sensor=None)
    assert ctrl.outdoor_temp() == -1.0
    assert ctrl.outdoor_source == "boiler_stale"


def test_weather_entity_uses_attribute():
    ctrl, hass, be = _ctrl(outdoor_sensor="weather.home")
    be._outdoor = None
    st = MagicMock()
    st.state = "sunny"
    st.attributes = {"temperature": 11.2}
    hass.states.get.return_value = st
    assert ctrl.outdoor_temp() == 11.2
    assert ctrl.outdoor_source == "ha"


def test_no_source_returns_none():
    ctrl, hass, be = _ctrl(outdoor_sensor=None)
    be._outdoor = None
    assert ctrl.outdoor_temp() is None
    assert ctrl.outdoor_source is None
