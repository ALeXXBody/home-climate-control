"""Solar fallback: HA sun position as a conservative proxy for lux."""

from unittest.mock import MagicMock

from custom_components.home_climate_control.solar import (
    COMFORT_OFFSET_C,
    SUN_OFFSET_C,
    SolarGain,
)


def _elev_series(sg, elevs):
    for e in elevs:
        sg.update_sun(e)


def test_sun_fallback_activates_only_high_sun_sustained():
    sg = SolarGain()
    _elev_series(sg, [40.0] * 8)
    assert sg.active is True
    assert sg.lux_ema is None                     # purely sun-driven
    assert sg.as_dict()["source"] == "sun"
    # dropping to a low winter sun turns it back off (hysteresis)
    _elev_series(sg, [10.0] * 20)
    assert sg.active is False


def test_sun_fallback_never_fires_after_dusk():
    sg = SolarGain()
    _elev_series(sg, [-5.0] * 10)
    assert sg.active is False
    assert sg.offset_contribution == 0.0


def test_sun_offset_weaker_than_lux_offset():
    high = [40.0] * 8
    sg_sun = SolarGain()
    _elev_series(sg_sun, high)
    sg_lux = SolarGain()
    for _ in range(8):
        sg_lux.update(6000.0)
    assert sg_sun.active and sg_lux.active
    assert abs(sg_sun.offset_contribution) == SUN_OFFSET_C
    assert abs(sg_lux.offset_contribution) == COMFORT_OFFSET_C
    assert SUN_OFFSET_C < COMFORT_OFFSET_C


def test_measured_lux_beats_sun_proxy():
    sg = SolarGain()
    _elev_series(sg, [40.0] * 8)          # sun-detector active
    sg.sun_elev = 40.0
    sg.update(200.0)                      # lux says: indoor daylight only
    for _ in range(20):
        sg.update(200.0)
    # lux EMA now rules: trim switches off despite high elevation
    assert sg.active is False
    d = sg.as_dict()
    assert d["source"] == "lux"


def test_central_tick_skips_lux_rooms_and_feeds_others():
    """Rooms with a lux sensor never receive sun updates."""
    from custom_components.home_climate_control.central import CentralController

    ctrl = object.__new__(CentralController)
    hass = MagicMock()
    st = MagicMock()
    st.attributes = {"elevation": 37.0}
    hass.states.get = lambda eid: st if eid == "sun.sun" else None

    no_lux = MagicMock(_lux_sensor=None)
    no_lux.solar = SolarGain()
    no_lux.solar.sun_elev = None
    with_lux = MagicMock(_lux_sensor="sensor.lux")
    with_lux.solar = SolarGain()
    with_lux.solar.sun_elev = None
    ctrl.zones = [no_lux, with_lux]
    ctrl.hass = hass
    CentralController._solar_sun_tick(ctrl)
    assert no_lux.solar.sun_elev == 37.0     # fed
    assert with_lux.solar.sun_elev is None   # untouched
