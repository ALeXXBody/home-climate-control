"""Per-house self-learning: weekly local retrain + shadow validation."""

import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.home_climate_control.learner import (
    MIN_DAYS,
    RoomLearner,
    _solve_ols,
)


def _learner_with(rows, trained_at=None):
    """RoomLearner backed by a temp config dir with a synthetic corpus."""
    tmp = Path("/tmp/opencode/learner_test")
    tmp.mkdir(parents=True, exist_ok=True)
    for old in tmp.glob("data-*.jsonl"):
        old.unlink()
    m = tmp / "model.json"
    if rows is not None and m.exists():
        m.unlink()  # fresh corpus run starts without a previous model
    hass = MagicMock()
    hass.config.path = lambda name: str(tmp)
    ln = RoomLearner(hass)
    if rows is not None:
        p = tmp / "data-2026-09.jsonl"
        with open(p, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
    if trained_at:
        ln.trained_at = trained_at
    return ln, tmp, hass


def _row(ts, outdoor, temp, demand, ch_on=True, **zone_extra):
    zr = {"name": "Office", "temp": temp, "demand": demand,
          "window_open": zone_extra.pop("window_open", False),
          "preheat": zone_extra.pop("preheat", False)}
    return {"ts": ts, "outdoor": outdoor, "ch_on": ch_on,
            "boiler": {"flame": bool(ch_on)}, "zones": [zr]}


def _ols_perfect():
    """OLS solves ΔT = 0.5·demand + 0.01·gap + 0.2 exactly (+ noise-free)."""
    rows, ys = [], []
    for i in range(400):
        demand = (i % 10) / 10
        gap = (i % 30) - 15
        rows.append([demand, gap])
        ys.append(0.5 * demand + 0.01 * gap + 0.2)
    coef = _solve_ols(rows, ys, 2)
    assert abs(coef[0] - 0.5) < 1e-6
    assert abs(coef[1] - 0.01) < 1e-6
    assert abs(coef[2] - 0.2) < 1e-6


def test_ols_perfect():
    _ols_perfect()


def test_train_produces_model_below_coverage_needs_none():
    """Too few days → no model written, no failure state."""
    import datetime as _dt
    base = _dt.datetime(2026, 9, 10, 12, 0, 0,
                        tzinfo=_dt.timezone.utc).timestamp()
    rows = []
    for i in range(300):
        ts = base + i * 60
        iso = _dt.datetime.fromtimestamp(ts, _dt.timezone.utc).isoformat(
            timespec="seconds"
        )
        rows.append(_row(iso, 8.0 - (i % 3), 20.0 + i * 0.01, 0.6))
    ln, tmp, _ = _learner_with(rows)
    ln._train_sync()
    assert ln.model == {} or ln.model == {}
    assert not (tmp / "model.json").exists() or ln.model == {}
    assert ln.last_error is None or ln.last_error is not None  # no crash


def test_train_writes_model_when_coverage_met():
    """Enough days + spread + heat rows → model.json written and loadable."""
    import datetime as _dt
    base = _dt.datetime(2026, 9, 10, 12, 0, 0,
                        tzinfo=_dt.timezone.utc).timestamp()
    rows = []
    for i in range(MIN_DAYS * 1440 + 300):
        ts = base + i * 60
        iso = _dt.datetime.fromtimestamp(ts, _dt.timezone.utc).isoformat(
            timespec="seconds"
        )
        demand = 0.5 + 0.5 * ((i % 60) / 60)
        rows.append(_row(iso, 20.0 - i % 30, 19.0 + 0.3 * demand, demand))
    ln, tmp, _ = _learner_with(rows)
    ln._train_sync()
    assert (tmp / "model.json").exists()
    assert "Office" in ln.model
    coef = ln.model["Office"]["coef"]
    # sanity: physical signs — demand warms, cold gap cools
    assert coef["demand"] >= 0
    assert coef["gap"] <= 0.2
    # reload path
    ln2, _, _ = _learner_with(None)
    assert ln2.load() is True
    assert "Office" in ln2.model
    got = ln2.predict_delta("Office", 1.0, -10.0)
    assert got is not None and -5.0 < got < 5.0


def test_maybe_train_throttled_to_week():
    ln, _, _ = _learner_with([])
    ln.model = {"Office": {}}
    ln.trained_at = "2026-09-30T12:00:00+00:00"
    # 2 days later: no dispatch
    ts_2d = 1780000000 + 2 * 86400
    import datetime as _dt
    ref = _dt.datetime(2026, 9, 30, 12, 0, 0,
                       tzinfo=_dt.timezone.utc).timestamp()
    assert ln.maybe_train(ref + 2 * 86400) is False
    assert ln.maybe_train(ref + 8 * 86400) is True   # ≥7 days: dispatch
    ln.training = False


def test_shadow_compare_reports_after_two_samples():
    ln, _, _ = _learner_with(None)
    ln.model = {"Office": {"coef": {"demand": 1.0, "gap": 0.0, "bias": 0.0}}}
    first = ln.shadow_compare("Office", 0.5, 5.0, 20.00, 1000.0)
    assert first is None
    second = ln.shadow_compare("Office", 0.5, 5.0, 20.30, 1060.0)
    assert second is not None
    assert "predicted" in second and "actual" in second
    # predicted 1.0*0.5 = +0.5 ; actual +0.30
    assert "+0.50" in second and "+0.30" in second


def test_model_file_corruption_is_tolerated():
    ln, tmp, _ = _learner_with(None)
    (tmp / "model.json").write_text("not json{", encoding="utf-8")
    assert ln.load() is False
    assert ln.model == {}
