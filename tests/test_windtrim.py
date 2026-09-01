"""Wind trim (bounded curve outdoor correction) tests."""

import pytest
from unittest.mock import MagicMock

from custom_components.home_climate_control.windtrim import (
    WindTrimmer,
    wind_trim_c,
)


def test_wind_trim_formula_bounds():
    # 0 wind → no trim
    assert wind_trim_c(0, 3.0) == 0.0
    # 10 km/h → 0.25 * 10^0.9 ≈ 1.99
    assert wind_trim_c(10, 3.0) == pytest.approx(1.99, abs=0.01)
    # 30 km/h would be ~5.2 → clamped at cap
    assert wind_trim_c(30, 3.0) == 3.0
    # negative / None → 0
    assert wind_trim_c(-5, 3.0) == 0.0
    assert wind_trim_c(None, 3.0) == 0.0
    # small cap respected even at low wind
    assert wind_trim_c(10, 1.0) == 1.0


def test_trimmer_disabled_is_passthrough():
    t = WindTrimmer(None, "weather.home", enabled=False)
    t.refresh()
    assert t.trim_c == 0.0
    assert t.effective(5.0) == 5.0
    assert t.effective(None) is None


def test_trimmer_missing_entity_or_no_wind():
    hass = MagicMock()
    hass.states.get.return_value = None
    t = WindTrimmer(hass, "weather.home", enabled=True)
    t.refresh()
    assert t.trim_c == 0.0
    # entity without wind_speed attribute
    st = MagicMock()
    st.state = "sunny"
    st.attributes = {}
    hass.states.get.return_value = st
    t.refresh()
    assert t.trim_c == 0.0
    # unknown/unavailable state
    st2 = MagicMock()
    st2.state = "unavailable"
    st2.attributes = {"wind_speed": 20}
    hass.states.get.return_value = st2
    t.refresh()
    assert t.trim_c == 0.0


def test_trimmer_applies_trim():
    hass = MagicMock()
    st = MagicMock()
    st.state = "sunny"
    st.attributes = {"wind_speed": 20}  # 0.25*20^0.9 ≈ 3.67 → clamped 3.0
    hass.states.get.return_value = st
    t = WindTrimmer(hass, "weather.home", enabled=True, max_delta=3.0)
    t.refresh()
    assert t.wind_kmh == 20
    assert t.trim_c == 3.0
    assert t.effective(5.0) == 2.0
    # mild wind not clamped
    st.attributes = {"wind_speed": 10}
    t.refresh()
    assert 1.9 < t.trim_c < 2.1
    assert t.effective(5.0) == pytest.approx(5.0 - t.trim_c, abs=0.05)


def test_trimmer_tolerates_bad_hass():
    t = WindTrimmer(MagicMock(states=None), "weather.home", enabled=True)
    t.refresh()
    assert t.trim_c == 0.0
    assert t.effective(4.0) == 4.0


def test_controller_uses_effective_outdoor():
    """Curve-facing outdoor gets the trim; raw outdoor stays for display."""
    from custom_components.home_climate_control.central import CentralController

    hass = MagicMock()
    st = MagicMock()
    st.state = "cloudy"
    st.attributes = {"wind_speed": 20}
    hass.states.get.return_value = st
    backend = MagicMock()
    backend.outdoor_temp = 5.0
    backend.outdoor_age_s = 0
    backend.flame_on = False
    backend.ch_active = False

    c = CentralController(
        hass,
        backend,
        curve_coeff=1.0,
        design_outdoor=-10.0,
        min_flow=25,
        max_flow=75,
        wind_entity="weather.home",
        wind_enabled=True,
        wind_max_delta=3.0,
    )
    # raw resolution path untouched
    assert c.outdoor_temp() == 5.0
    assert c.outdoor_source == "boiler"
    # refresh reads wind from the weather entity, trim reduces what the curve sees
    c.windtrim.refresh()
    assert c.windtrim.effective(5.0) == 2.0
    diag = c.diagnostics()
    assert diag["wind_trim"]["trim_c"] == 3.0
    assert diag["outdoor_effective"] == 2.0


def test_trimmer_unit_conversion():
    hass = MagicMock()

    def with_wind(wind, unit):
        st = MagicMock()
        st.state = "sunny"
        st.attributes = {"wind_speed": wind, "wind_speed_unit": unit}
        hass.states.get.return_value = st
        t = WindTrimmer(hass, "weather.home", enabled=True, max_delta=6.0)
        t.refresh()
        return t.wind_kmh

    assert with_wind(20.9, "km/h") == 20.9
    assert with_wind(5.0, "m/s") == 18.0
    assert with_wind(10.0, "mph") == pytest.approx(16.1, abs=0.05)
    assert with_wind(10.0, "ft/s") == pytest.approx(11.0, abs=0.05)
    # unknown unit → passthrough
    assert with_wind(7.0, "furlongs/fortnight") == 7.0


def test_entity_selection_enables_compensation():
    """No separate toggle: picking the entity enables the trim."""
    from custom_components.home_climate_control.central import CentralController

    hass = MagicMock()
    st = MagicMock()
    st.state = "cloudy"
    st.attributes = {"wind_speed": 20}
    hass.states.get.return_value = st
    backend = MagicMock()
    backend.outdoor_temp = 5.0
    backend.outdoor_age_s = 0

    c = CentralController(
        hass, backend, curve_coeff=1.0, design_outdoor=-10.0,
        min_flow=25, max_flow=75,
        wind_entity="weather.home", wind_enabled=True, wind_max_delta=3.0,
    )
    assert c.windtrim.enabled is True
    c.windtrim.refresh()
    assert c.windtrim.trim_c == 3.0
