"""Weighted fit, shadow scorecard, model versioning/rollback."""

import json
from pathlib import Path
from unittest.mock import MagicMock

from custom_components.home_climate_control.learner import (
    MIN_DAYS,
    _solve_ols,
    RoomLearner,
)
from test_learner import _learner_with, _row


def test_weighted_ols_favours_high_weight_samples():
    """Weighted OLS: weights pull the fit towards heavily-weighted rows."""
    xs = [[0.0], [1.0], [0.0], [1.0]]
    ys = [0.0, 1.0, 0.9, 1.0]        # the last idle row is an outlier
    no_w = _solve_ols(xs, ys, 1)
    big = _solve_ols(xs, ys, 1, weights=[1.0, 1.0, 1.0, 50.0])
    assert big[0] > no_w[0]


def test_heated_windows_dominate_the_fit():
    """A room that heats briefly per hour still learns its heating rate."""
    import datetime as _dt
    base = _dt.datetime(2026, 9, 10, 12, 0, 0,
                        tzinfo=_dt.timezone.utc).timestamp()
    rows = []
    t_sim = 19.0
    for i in range(MIN_DAYS * 1440 + 700):
        ts = base + i * 60
        iso = _dt.datetime.fromtimestamp(ts, _dt.timezone.utc).isoformat(
            timespec="seconds"
        )
        on = (i % 60) < 10           # heat 10 min per hour only
        demand = 1.0 if on else 0.0
        outdoor = 6.0 + 10.0 * ((i // 1440) % 2)
        rows.append(_row(iso, outdoor, round(t_sim, 3), demand, ch_on=on))
        t_sim += 0.06 if on else 0.0   # +0.36 °C/10min while heating
    ln, tmp, _ = _learner_with(rows)
    ln._train_sync()
    assert "Office" in ln.model
    m = ln.model["Office"]
    assert m.get("weighted") is True
    # truth +0.36 °C/10min at demand 1.0; idle windows weigh only 0.25
    assert 0.2 <= m["coef"]["demand"] <= 0.6, m["coef"]


def test_shadow_scorecard_reports_skill():
    ln, _, _ = _learner_with(None)
    ln.model = {"Office": {"coef": {"demand": 1.0, "gap": 0.0, "bias": 0.0}}}
    # model says +0.5 °C/10min ; reality exactly that over exactly 600 s
    ln.shadow_compare("Office", 0.5, 5.0, 20.00, 1000.0)
    ln.shadow_compare("Office", 0.5, 5.0, 20.50, 1600.0)
    sc = ln.shadow_scores()["Office"]
    assert sc["n"] == 1
    assert sc["model_rmse"] < 0.01
    assert sc["baseline_rmse"] > sc["model_rmse"]
    assert 0.9 <= sc["skill"] <= 1.0
    # a second, badly wrong prediction drags the skill down
    ln.shadow_compare("Office", 0.0, 5.0, 20.50, 2200.0)
    ln.shadow_compare("Office", 0.0, 5.0, 21.20, 2800.0)   # reality ≈+0.70
    sc = ln.shadow_scores()["Office"]
    assert sc["n"] == 3                       # two compare-pairs + one store-then-compare
    assert sc["skill"] < 0.6


def _trained_rollback_case(tmp: Path, prev_rmse, new_rmse):
    """Build a corpus whose fit lands at a controlled rmse via noise."""
    rooms = {
        "Office": {
            "coef": {"demand": 0.5, "gap": -0.01, "bias": 0.1},
            "n": 3000, "rmse": prev_rmse, "mode": "full",
            "scale_s": 600, "weighted": True,
        }
    }
    (tmp / "model.json").write_text(
        json.dumps({"version": 1, "trained_at": "2026-10-05T10:00:00+00:00",
                    "rooms": rooms}),
        encoding="utf-8",
    )


def test_rollback_keeps_prev_when_new_worse():
    """Same-scale refit worse than stored → previous model is kept."""
    import datetime as _dt
    tmp = Path("/tmp/opencode/learner_roll_t")
    tmp.mkdir(parents=True, exist_ok=True)
    prev_rmse, new_rmse = 0.10, 0.80   # craft corpus noise so new ≈ 0.8
    _trained_rollback_case(tmp, prev_rmse, new_rmse)
    base = _dt.datetime(2026, 9, 10, 12, 0, 0,
                        tzinfo=_dt.timezone.utc).timestamp()
    rows = []
    import random
    random.seed(7)
    t_sim = 19.0
    for i in range(MIN_DAYS * 1440 + 700):
        ts = base + i * 60
        iso = _dt.datetime.fromtimestamp(ts, _dt.timezone.utc).isoformat(
            timespec="seconds"
        )
        demand = 1.0 if (i // 30) % 2 == 0 else 0.0
        outdoor = 5.0 + 10.0 * ((i // 1440) % 2)
        noise = random.uniform(-1.2, 1.2)   # big jitter → high new rmse
        rows.append(_row(iso, outdoor, round(t_sim + noise, 3), demand))
        t_sim += 0.05 * demand
    hass = MagicMock()
    hass.config.path = lambda name: str(tmp)
    ln = RoomLearner(hass)
    assert ln.load() is True
    old_entry = ln.model["Office"]
    ln._train_sync()
    assert ln.model["Office"] is old_entry          # kept previous model
    blob = json.loads((tmp / "model.json").read_text(encoding="utf-8"))
    assert blob["coverage"]["kept_prev"] >= 1
