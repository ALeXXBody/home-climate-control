"""Dead-time estimation: stopwatch armed at heat start, stopped on rise."""

import pytest

from custom_components.home_climate_control.deadtime import (
    DT_MAX_S,
    DeadTimeEstimator,
)

M = 60.0


def est():
    return DeadTimeEstimator(None)  # no store: pure logic


def test_measures_delay_from_arm_to_sustained_rise():
    e = est()
    e.arm(["Living"], ts=1000.0, temps={"Living": 19.0})
    t, temp = 1000.0, 19.0
    res = None
    # boiler transport lag ~7 min of continued fall, then recovery
    for i in range(1, 8):
        t += M
        temp -= 0.05
        res = e.observe("Living", t, temp) or res
    for i in range(4):
        t += M
        temp += 0.10
        res = e.observe("Living", t, temp) or res
    assert res is not None
    assert 9 <= res / 60.0 <= 12  # fell until min 7, rose from min 8-11
    assert e.seconds_for("Living") == pytest.approx(res)
    # stopwatch disarmed after measurement
    assert e.rooms["Living"].armed is False


def test_ema_smooths_second_measurement():
    e = est()
    e.arm(["A"], ts=0.0, temps={"A": 19.0})
    t = 0.0
    temp = 18.95
    for _ in range(3):
        t += M
        temp += 0.1
        e.observe("A", t, temp)
    first = e.estimates["A"]
    # second event responds faster (two +100 s samples -> 200 s)
    e.arm(["A"], ts=t, temps={"A": temp})
    for _ in range(3):
        t += 100.0
        temp += 0.1
        e.observe("A", t, temp)
    # Second event: two +100 s samples -> response after 200 s.
    expected = first + 0.30 * (200.0 - first)
    assert e.estimates["A"] == pytest.approx(expected)


def test_disarm_when_heat_ends_before_response():
    e = est()
    e.arm(["Hall"], ts=0.0, temps={"Hall": 17.0})
    e.disarm_all()
    assert e.observe("Hall", 600.0, 18.0) is None
    assert "Hall" not in e.estimates


def test_out_of_range_measurements_discarded():
    e = est()
    # responds suspiciously fast (< DT_MIN_S): ignored
    e.arm(["Fast"], ts=0.0, temps={"Fast": 19.0})
    e.observe("Fast", 20.0, 19.02)
    e.observe("Fast", 40.0, 19.12)
    assert "Fast" not in e.estimates
    # responds absurdly slow (> DT_MAX_S): ignored
    e.arm(["Slow"], ts=0.0, temps={"Slow": 19.0})
    e.observe("Slow", DT_MAX_S - 20, 19.09)
    e.observe("Slow", DT_MAX_S + 30, 19.19)
    assert "Slow" not in e.estimates


def test_baseline_anchor_without_starting_temp():
    e = est()
    e.arm(["Bedroom"], ts=0.0)  # controller had no reading yet
    e.observe("Bedroom", 120.0, 18.0)   # anchors baseline
    e.observe("Bedroom", 240.0, 18.10)
    e.observe("Bedroom", 360.0, 18.20)
    assert "Bedroom" in e.estimates


def test_as_dict_shape():
    e = est()
    e.arm(["Z"], ts=0.0, temps={"Z": 19.0})
    e.observe("Z", 400.0, 19.1)
    e.observe("Z", 800.0, 19.2)
    d = e.as_dict()
    assert d["enabled"] is True
    assert d["rooms"]["Z"]["minutes"] == pytest.approx(800.0 / 60.0, abs=0.1)
    assert d["rooms"]["Z"]["measuring"] is False
