"""Insulation score: weather-normalized loss factor from cool-down stretches."""

import pytest

from custom_components.home_climate_control.insulation import (
    InsulationScorer,
    label_for,
)

M = 60.0


def feed_stretch(s, zone, t0, tin, tout, rate_cph, pairs=5, step_s=22 * 60):
    """Feed one continuous cooling stretch; return the last estimate."""
    res = None
    t, temp = t0, tin
    for _ in range(pairs):
        t += step_s
        temp -= rate_cph * (step_s / 3600.0)
        res = s.observe(zone, t, temp, tout, cooling=True) or res
    return res


def test_loss_factor_normalizes_by_delta_t():
    s = InsulationScorer(None)
    # 25 K gap, 1 °C/h loss -> k ≈ 0.04
    k = feed_stretch(s, "Salon", 1000.0, 20.0, -5.0, rate_cph=1.0)
    assert k == pytest.approx(0.04, abs=0.01)


def test_same_rate_mild_day_scores_worse():
    s = InsulationScorer(None)
    # Same 1 °C/h but only a 10 K gap -> k ≈ 0.10 (leakier).
    k = feed_stretch(s, "Attic", 1000.0, 20.0, 10.0, rate_cph=1.0)
    assert k == pytest.approx(0.10, abs=0.02)


def test_labels_order():
    assert label_for(0.02) == "excellent"
    assert label_for(0.05) == "good"
    assert label_for(0.10) == "fair"
    assert label_for(0.30) == "poor"


def test_stretch_break_resets_anchor_keeps_score():
    s = InsulationScorer(None)
    feed_stretch(s, "Hall", 1000.0, 20.0, -5.0, rate_cph=1.0)
    first = s.score_for("Hall")
    # heating resumes (cooling=False): anchor dropped, score retained
    s.observe("Hall", 9999.0, 21.5, -5.0, cooling=False)
    assert s.score_for("Hall") == first


def test_short_gaps_and_rising_temps_ignored():
    s = InsulationScorer(None)
    # too-fast sampling: no pair qualifies
    r1 = s.observe("A", 1000.0, 20.0, -5.0, cooling=True)
    r2 = s.observe("A", 1060.0, 19.98, -5.0, cooling=True)
    assert r1 is None and r2 is None and s.score_for("A") is None
    # temperature rising during 'cooling' flag: ignored as noise
    feed_stretch(s, "B", 1000.0, 18.0, -5.0, rate_cph=-2.0, pairs=3)
    assert s.score_for("B") is None


def test_as_dict_shape_and_persistence_payload():
    s = InsulationScorer(None)
    feed_stretch(s, "Kitchen", 1000.0, 20.0, -5.0, rate_cph=1.6)
    d = s.as_dict()
    assert d["enabled"] is True
    room = d["rooms"]["Kitchen"]
    assert room["label"] in ("excellent", "good")
    assert room["k"] == pytest.approx(0.064, abs=0.03)
