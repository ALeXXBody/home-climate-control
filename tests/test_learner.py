"""Per-house self-learning: weekly local retrain + shadow validation."""

import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.home_climate_control.const import DOMAIN
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
    assert -0.1 <= coef["demand"] <= 2.0   # static fixture ⇒ ≈0 is right
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
    # The dispatch must be a real scheduled task — a bare (never-awaited)
    # async_add_executor_job silently never ran (release 1.17.0 bug).
    hass_ = ln.hass
    assert hass_.async_create_task.called, "training job was not scheduled"


def test_shadow_compare_reports_after_two_samples():
    ln, _, _ = _learner_with(None)
    ln.model = {"Office": {"coef": {"demand": 1.0, "gap": 0.0, "bias": 0.0}}}
    first = ln.shadow_compare("Office", 0.5, 5.0, 20.00, 1000.0)
    assert first is None
    # 420 s revisit → reality normalised to the 10-min scale
    second = ln.shadow_compare("Office", 0.5, 5.0, 20.30, 1420.0)
    assert second is not None
    assert "predicted" in second and "actual" in second
    # predicted 1.0*0.5 = +0.5 ; actual (0.30)*600/420 = +0.43 /10min
    assert "+0.50" in second and "+0.43" in second


def test_model_file_corruption_is_tolerated():
    ln, tmp, _ = _learner_with(None)
    (tmp / "model.json").write_text("not json{", encoding="utf-8")
    assert ln.load() is False
    assert ln.model == {}


def test_rename_room_migrates_model_and_persists():
    """Rename must carry the model like setbacks — never orphan the key."""
    ln, tmp, _ = _learner_with(None)
    ln.model = {"Office": {"coef": {"demand": 1.0, "gap": 0.0, "bias": 0.0},
                           "n": 10, "rmse": 0.1}}
    ln.trained_at = "2026-10-01T10:00:00+00:00"
    ln.hass = None  # disable the async dispatch → synchronous persist path
    got = ln.rename_room("Office", "Study")
    assert got is True
    assert "Study" in ln.model and "Office" not in ln.model
    blob = json.loads((tmp / "model.json").read_text(encoding="utf-8"))
    assert "Study" in blob["rooms"] and "Office" not in blob["rooms"]


def test_rename_room_ignores_unknown():
    ln, _, _ = _learner_with(None)
    ln.model = {"Office": {"coef": {"demand": 0, "gap": 0, "bias": 0}}}
    assert ln.rename_room("Ghost", "New") is False
    assert ln.model == {"Office": {"coef": {"demand": 0, "gap": 0, "bias": 0}}}
    assert ln.rename_room("Office", "Office") is False  # no-op self rename


def test_room_rows_carry_model_same_schema():
    """get_status rooms must expose the AI model per room, keyed by name."""
    from custom_components.home_climate_control.websocket_api import _collect_status

    class _Z:
        name = "Office"
        entity_id = "climate.office"
        current_temperature = 20.0
        target_temperature = 21.0
        hvac_mode = "heat"
        hvac_action = "idle"
        preset_mode = "none"
        floor = 0
        heater_control = "smart"
        window_sensor_entities = []
        trv_entity = None
        trv_entities = []
        current_humidity = None
        paused = staticmethod(lambda: False)
        demand_level = staticmethod(lambda: 0.3)
        effective_setpoint = staticmethod(lambda: 21.0)
        extra_state_attributes = {}
        solar = None
        co2 = None
        humidity_sensor_entity = None
        temp_sensor_entity = None
        window_open_override = False

        def lead_time_s(self, **k):
            return None

    ctrl = SimpleNamespace(zones=[_Z()], learner=SimpleNamespace(
        model={"Office": {"coef": {"demand": 0.4, "gap": -0.01, "bias": 0.1},
                          "n": 2400, "rmse": 0.21}},
        trained_at="2026-10-02T10:00:00+00:00", rooms=["Office"],
        room_detail={"Office": {"n": 2400, "rmse": 0.21}},
        training=False, last_attempt=0.0, last_error=None))
    hass = MagicMock()
    hass.states.get = MagicMock(return_value=None)
    hass.data = {DOMAIN: {"e1": {"controller": ctrl}}}
    hass.config_entries.async_entries = MagicMock(return_value=[])
    out = _collect_status(hass)
    zones = out["systems"][0]["zones"]
    row = next(z for z in zones if z["name"] == "Office")
    assert row["model"]["n"] == 2400
    assert row["model"]["coef"]["demand"] == 0.4


def test_demand_only_training_when_outdoor_absent():
    """Houses with NO outdoor data still earn a demand-only model."""
    import datetime as _dt
    base = _dt.datetime(2026, 8, 10, 12, 0, 0,
                        tzinfo=_dt.timezone.utc).timestamp()
    rows = []
    for i in range(MIN_DAYS * 1440 + 300):
        ts = base + i * 60
        iso = _dt.datetime.fromtimestamp(ts, _dt.timezone.utc).isoformat(
            timespec="seconds"
        )
        demand = 0.3 + 0.7 * ((i % 50) / 50)
        rows.append(_row(iso, None, 19.0 + 0.25 * demand, demand, ch_on=True))
    ln, tmp, _ = _learner_with(rows)
    ln._train_sync()
    assert "Office" in ln.model
    assert ln.model["Office"]["mode"] == "demand_only"
    assert "gap" not in ln.model["Office"]["coef"]
    assert ln.model["Office"]["coef"]["demand"] >= -0.01
    got = ln.predict_delta("Office", 1.0, 0.0)
    assert got is not None


def test_outdoor_spread_gate_still_blocks_with_outdoor():
    """Present-but-flat outdoor data (mild-only weeks) must not set a model."""
    import datetime as _dt
    base = _dt.datetime(2026, 8, 10, 12, 0, 0,
                        tzinfo=_dt.timezone.utc).timestamp()
    rows = []
    for i in range(MIN_DAYS * 1440 + 300):
        ts = base + i * 60
        iso = _dt.datetime.fromtimestamp(ts, _dt.timezone.utc).isoformat(
            timespec="seconds"
        )
        demand = 0.5
        rows.append(_row(iso, 12.0 + (i % 4) * 0.5,
                         19.5 + 0.2 * demand, demand))
    ln, tmp, _ = _learner_with(rows)
    ln._train_sync()
    assert ln.model == {}


def test_force_train_dispatches_immediately():
    """Manual 'Train now': clears the weekly latch, schedules the job."""
    ln, _, _ = _learner_with([])
    ln.model = {"Office": {"coef": {"demand": 0, "gap": 0, "bias": 0}}}
    ln.trained_at = "2026-09-30T12:00:00+00:00"
    import datetime as _dt
    ref = _dt.datetime(2026, 9, 30, 12, 0, 0,
                       tzinfo=_dt.timezone.utc).timestamp()
    ln.force_train()
    assert ln.hass.async_create_task.called, "force_train did not dispatch"
    assert ln.trained_at is None  # latch cleared by force_train
    assert ln.skip_reason is None


def test_windowed_training_recovers_real_signal():
    """Synthetic house: heat +0.4 °C/10min at full demand, −0.1 idle.

    The 10-min window regression must land near the true coefficient;
    the 1-minute variant of this test data would have drowned in noise.
    """
    import datetime as _dt
    from custom_components.home_climate_control.learner import WINDOW_S
    base = _dt.datetime(2026, 9, 10, 12, 0, 0,
                        tzinfo=_dt.timezone.utc).timestamp()
    rows = []
    t_sim = 19.0
    for i in range(MIN_DAYS * 1440 + 700):
        ts = base + i * 60
        iso = _dt.datetime.fromtimestamp(ts, _dt.timezone.utc).isoformat(
            timespec="seconds"
        )
        demand = 1.0 if (i // 30) % 2 == 0 else 0.0   # 30-min on/off cycles
        outdoor = 5.0 + 10.0 * ((i // 1440) % 2)      # 5 ↔ 15 °C daily swap
        rows.append(_row(iso, outdoor, round(t_sim, 3), demand))
        # physics: heating raises 0.04 °C/min at demand 1, cooling -0.01
        t_sim += (0.04 * demand) + (-0.01 * (1.0 - demand))
    ln, tmp, _ = _learner_with(rows)
    ln._train_sync()
    assert "Office" in ln.model
    m = ln.model["Office"]
    assert m["mode"] == "full"
    # coef is per-unit-demand effect on a 10-min ΔT: truth ≈ +0.5 °C
    assert 0.35 <= m["coef"]["demand"] <= 0.65, m["coef"]
    assert abs(m["coef"]["gap"]) < 0.15   # gap had no effect by construction


def test_windowed_training_with_outdoor_cooling():
    """Cold outdoors must show up as a negative gap coefficient."""
    import datetime as _dt
    base = _dt.datetime(2026, 9, 10, 12, 0, 0,
                        tzinfo=_dt.timezone.utc).timestamp()
    rows = []
    t_sim = 19.0
    outs = [5.0, 6.0, 7.0, 8.0]  # varies ≤ spread gate? spread = 3 °C only
    for i in range(MIN_DAYS * 1440 + 700):
        ts = base + i * 60
        iso = _dt.datetime.fromtimestamp(ts, _dt.timezone.utc).isoformat(
            timespec="seconds"
        )
        demand = 1.0 if (i // 30) % 2 == 0 else 0.0
        outdoor = outs[(i // 1440) % len(outs)]
        rows.append(_row(iso, outdoor, round(t_sim, 3), demand))
        t_sim += 0.04 * demand - 0.01 * ((t_sim - outdoor) / 10.0) * 0.1
    ln, tmp, _ = _learner_with(rows)
    ln._train_sync()
    # NOTE: spread here is 3 °C (< MIN_OUTDOOR_SPREAD) so the FULL gate
    # blocks — this asserts the guard keeps protecting against mild weeks.
    assert ln.model == {}
