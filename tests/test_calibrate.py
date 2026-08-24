"""Bootstrap heat-rate calibration: pure-logic behaviour + setback injection."""

import pytest

from custom_components.home_climate_control.calibrate import (
    MAX_SESSION_S,
    MIN_SPAN_S,
    TARGET_GAIN_C,
    RoomCalibrator,
)
from custom_components.home_climate_control.setback import SetbackLearner

H = 3600.0


def feed(cal, zone, hours, rate_cph, step_s=300, temp0=18.0):
    """Simulate a room warming at rate_cph; return the final observe() result."""
    res = None
    t = 1000.0
    temp = temp0
    cal.observe(zone, t, temp)
    steps = int(hours * H / step_s)
    for _ in range(steps):
        t += step_s
        temp += rate_cph * (step_s / H)
        res = cal.observe(zone, t, temp) or res
    return res


def test_measures_rate_when_target_gain_reached():
    cal = RoomCalibrator()
    cal.start("Living Room", ts=1000.0, temp=18.0)
    assert cal.active()
    # 2 °C/h for one hour = 2 °C gain >= TARGET_GAIN_C (1.5).
    res = feed(cal, "Living Room", hours=1.05, rate_cph=2.0)
    assert res is not None and res["status"] == "done"
    assert abs(res["rate_cph"] - 2.0) < 0.15
    assert not cal.active()


def test_ignores_other_zones():
    cal = RoomCalibrator()
    cal.start("Bedroom", ts=1000.0, temp=18.0)
    assert feed(cal, "Living Room", hours=3.0, rate_cph=9.0) is None
    assert cal.active()  # still measuring the bedroom


def test_cancel_reports_no_rate():
    cal = RoomCalibrator()
    cal.start("Hall", ts=1000.0, temp=17.0)
    res = cal.cancel(ts=2000.0)
    assert res["status"] == "cancelled"
    assert "rate_cph" not in res
    assert not cal.active()


def test_timeout_with_usable_span_gives_partial_rate():
    cal = RoomCalibrator()
    cal.start("Attic", ts=1000.0, temp=16.0)
    # Slow room: 0.6 °C/h -> only ~0.9 °C after 90 min timeout, but span
    # exceeds MIN_SPAN_S so a partial rate is still reported.
    res = feed(cal, "Attic", hours=MAX_SESSION_S / H + 0.01, rate_cph=0.6, temp0=16.0)
    assert res is not None and res["status"] == "partial"
    assert abs(res["rate_cph"] - 0.6) < 0.1


def test_too_short_session_fails_without_rate():
    cal = RoomCalibrator()
    cal.start("Box Room", ts=1000.0, temp=20.0)
    res = cal.finish_partial(21.0, ts=1000.0 + MIN_SPAN_S / 2)
    assert res["status"] == "failed"
    assert "rate_cph" not in res


def test_double_start_rejected():
    cal = RoomCalibrator()
    cal.start("A")
    with pytest.raises(ValueError):
        cal.start("B")


def test_maybe_expire_uses_last_seen_temp():
    cal = RoomCalibrator()
    cal.start("Cellar", ts=0.0, temp=15.0)
    cal.observe("Cellar", 30 * 60, 15.4)  # last sample at minute 30
    res = cal.maybe_expire(MAX_SESSION_S + 10)
    assert res is not None and res["status"] == "partial"
    # Rate spans the whole session: 0.4 °C over ~1.5 h.
    assert abs(res["rate_cph"] - 0.27) < 0.05


def test_injection_seeds_setback_learner():
    learner = SetbackLearner(None)
    before = learner.offset_for("Kitchen", fallback=-2.0)
    assert before == -2.0  # fixed fallback while unmatured
    learner.inject_warm_rate("Kitchen", 4.0)
    st = learner.rooms["Kitchen"]
    assert st.warm_ema == pytest.approx(4.0)
    assert st.cycles == 1
    # Still below MIN_CYCLES: offset stays on fallback until more cycles land.
    assert learner.offset_for("Kitchen", -2.0) == -2.0


def test_injection_combines_with_existing_history():
    learner = SetbackLearner(None)
    learner.inject_warm_rate("Study", 4.0)
    learner.inject_warm_rate("Study", 6.0)
    st = learner.rooms["Study"]
    assert st.warm_ema == pytest.approx(4.0 + 0.35 * (6.0 - 4.0))
    assert st.cycles == 2
