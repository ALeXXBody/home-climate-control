"""Per-house self-learning: weekly local retrain on the house's own data.

The training-data logger (datalogger.py) records one snapshot per minute.
This module turns that corpus into per-room behaviour models — entirely
ON the installing box, learning THAT house from the day the app is
installed. Nothing is uploaded, nothing shared; every house trains its
own model over its own files.

Model (expecting to predict the next-minute temperature delta):
    ΔT ≈ a·demand + b·(outdoor − room_temp) + c
A closed-form ridge-regularised ordinary least squares (3 parameters)
keeps the maths trivial, CPU cost tiny and needs no third-party ML
libraries — a HA integration must never grow a heavy dependency.

Reliability rules (mirroring the logger):
- Training runs in the executor: file I/O never blocks the event loop.
- A failed run leaves the previous model.json untouched.
- Shadow mode first: predictions are LOGGED next to reality for weeks
  before any behaviour may ever consume them. Nothing in control changes
  from the model until it has proven itself.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant

from .datalogger import DIR_NAME

_LOGGER = logging.getLogger(__name__)

MODEL_FILE = "model.json"
RETRAIN_INTERVAL_S = 7 * 86400.0
MAX_ROWS = 200_000        # absolute cap; the corpus gets streamed anyway

# Coverage gates — a house that just installed MUST NOT train yet.
MIN_DAYS = 7
MIN_ROOM_ROWS = 2_000     # heat-relevant minutes (demand > 0 / CH on) per room
MIN_WINDOWS = 600         # ~10-min regression windows per room (~3.5 days)
MIN_OUTDOOR_SPREAD = 8.0  # °C; mild-only weeks must not set the model
WINDOW_S = 600            # training target: temperature change over ~10 min
WINDOW_TOL_S = 180        # ...accept samples WINDOW_S ± this


def _solve_ols(
    xs: list[list[float]],
    ys: list[float],
    k: int,
    weights: list[float] | None = None,
) -> list[float]:
    """Closed-form small ridge OLS: returns k+1 coefficients (last = bias).

    Optional per-sample weights: heating-weighted training uses them to
    make windows that actually ran the boiler count for more.
    """
    m = k + 1
    a = [[0.0] * m for _ in range(m)]
    b = [0.0] * m
    if weights is None or len(weights) != len(xs):
        weights = [1.0] * len(xs)
    for row, y, w in zip(xs, ys, weights):
        w = max(0.0, float(w))
        if w == 0.0:
            continue
        feat = [*row, 1.0]
        for i in range(m):
            xi = feat[i] * w
            b[i] += xi * y
            for j in range(m):
                a[i][j] += xi * feat[j]
    # tiny ridge on the diagonal keeps singular feature sets solvable
    for i in range(m):
        a[i][i] += 1e-6
    # gaussian elimination
    for col in range(m):
        piv = max(range(col, m), key=lambda r: abs(a[r][col]))
        if abs(a[piv][col]) < 1e-12:
            return [0.0] * m
        a[col], a[piv] = a[piv], a[col]
        b[col], b[piv] = b[piv], b[col]
        div = a[col][col]
        for j in range(col, m):
            a[col][j] /= div
        b[col] /= div
        for r in range(m):
            if r == col:
                continue
            f = a[r][col]
            if f == 0.0:
                continue
            for j in range(col, m):
                a[r][j] -= f * a[col][j]
            b[r] -= f * b[col]
    return b


class RoomLearner:
    """Loads, trains and serves the per-house room behaviour models."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._dir: Path | None = None
        try:
            self._dir = Path(hass.config.path(DIR_NAME))
        except Exception:  # noqa: BLE001
            self._dir = None
        self.model: dict[str, Any] = {}
        self.trained_at: str | None = None
        self.training: bool = False
        self.last_attempt: float = 0.0
        self.last_error: str | None = None
        self.skip_reason: str | None = None
        self.tick_count: int = 0
        # settable by the controller: current room names, used to prune
        # model.json keys whose room was renamed long ago (old corpus rows)
        self.known_rooms: set | None = None
        self._task_initial = None
        self._task_watch = None
        # rotating debug of one prediction-vs-actual per tick
        self._shadow_state: dict[str, Any] = {}
        # per-room shadow scorecard: model RMSE vs the do-nothing baseline
        # (predicting "no change"), on the 10-minute scale
        self._shadow_score: dict[str, dict[str, float]] = {}

    # -------------------------------------------------------------- loading
    def load(self) -> bool:
        """Load an existing model.json produced by a previous retrain."""
        assert self._dir is not None
        try:
            path = self._dir / MODEL_FILE
            blob = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(blob, dict) or "rooms" not in blob:
                return False
            rooms = blob["rooms"]
            if not isinstance(rooms, dict):
                return False
            for name, m in rooms.items():
                # every room needs coef + n; garbage rooms are dropped
                coef = (m or {}).get("coef")
                if not isinstance(coef, dict):
                    continue
                try:
                    a = float(coef.get("demand", 0.0))
                    bgap = float(coef.get("gap", 0.0))
                    c = float(coef.get("bias", 0.0))
                except (TypeError, ValueError):
                    continue
                m["coef"] = {"demand": a, "gap": bgap, "bias": c}
            self.model = rooms
            self.trained_at = blob.get("trained_at")
            return True
        except FileNotFoundError:
            return False
        except Exception:  # noqa: BLE001
            _LOGGER.debug("model.json unreadable", exc_info=True)
            self.last_error = "model.json unreadable"
            return False

    # ------------------------------------------------------------ prediction
    def predict_delta(self, room: str, demand: float, gap: float) -> float | None:
        """Predict next-minute ΔT (°C) for a room; None when not modeled.

        Demand-only models (houses without an outdoor sensor) ignore the
        gap argument — the coef dict simply has no 'gap' key.
        """
        m = self.model.get(room)
        if not isinstance(m, dict):
            return None
        coef = m.get("coef")
        if not isinstance(coef, dict):
            return None
        try:
            a = float(coef["demand"])
            c = float(coef["bias"])
        except (KeyError, TypeError, ValueError):
            return None
        if not all(isinstance(v, (int, float)) for v in (a, c)):
            return None
        bgap = coef.get("gap")
        if isinstance(bgap, (int, float)):
            return a * demand + float(bgap) * gap + c
        return a * demand + c

    # ------------------------------------------------------------ retraining
    def tick_seen(self, now: float) -> None:
        """Tick-path heartbeat: called before any decision, for diagnosis."""
        self.tick_count += 1

    def schedule_initial_train(self) -> None:
        """Dispatch the first retrain shortly after setup, decoupled from
        the control-loop tick path (a misbehaving tick can never stop the
        corpus from being used)."""
        if self._dir is None or self.hass is None:
            return
        async def _first():
            await __import__("asyncio").sleep(90.0)
            self.maybe_train()
        self._task_initial = self.hass.async_create_task(_first())

    def schedule_hourly_watch(self) -> None:
        """Repeat the weekly-due check hourly, also decoupled from ticks;
        the week throttle inside maybe_train keeps it cheap."""
        if self._dir is None or self.hass is None:
            return
        async def _watch():
            import asyncio as _aio
            while True:
                await _aio.sleep(3600.0)
                self.maybe_train()
        self._task_watch = self.hass.async_create_task(_watch())

    def async_stop(self) -> None:
        """Cancel the setup-time tasks: a config-entry reload must not leak
        immortal watch loops racing each other on model.json."""
        for attr in ("_task_initial", "_task_watch"):
            task = getattr(self, attr, None)
            if task is not None and hasattr(task, "cancel"):
                task.cancel()
                setattr(self, attr, None)

    def force_train(self) -> None:
        """Manual 'train now' (admin). Clears the weekly latch.

        Public WS command: home_climate_control/train_now.
        """
        if self._dir is None:
            self.skip_reason = "no data directory"
            return
        if self.training:
            return
        self.trained_at = None   # due immediately
        self.skip_reason = None
        self.maybe_train()

    def maybe_train(self, now: float | None = None) -> bool:
        """Cheap tick check: dispatch a retrain when the week is due."""
        if now is None:
            now = time.time()
        # Latch watchdog: an executor job that queued/hung must not wedge
        # learning permanently ("training in progress" forever).
        if self.training and self.last_attempt and (
            now - self.last_attempt > 2 * 3600.0
        ):
            self.training = False
            self.last_error = "training watchdog: recovered stuck latch"
        if self.training:
            self.skip_reason = "training in progress"
            return False
        if self._dir is None:
            self.skip_reason = "no data directory"
            return False
        last = 0.0
        if self.trained_at:
            try:
                last = datetime.fromisoformat(
                    self.trained_at.replace("Z", "+00:00")
                ).timestamp()
            except (ValueError, TypeError):
                last = 0.0
        if now - last < RETRAIN_INTERVAL_S:
            self.skip_reason = "next weekly run not due yet"
            return False
        self.last_attempt = now
        self.skip_reason = None
        self.training = True
        # Dispatch on the event loop properly: a bare async_add_executor_job
        # call creates the coroutine but nobody awaits it — the job (and the
        # training) would never actually run.
        self.hass.async_create_task(
            self.hass.async_add_executor_job(self._train_sync)
        )
        return True

    # ------------------------------------------------------- same schema
    def rename_room(self, old: str, new: str) -> bool:
        """Migrate a room's model to its new name (same schema as rooms).

        Fits the rename migration of setbacks/dead-time/insulation: learned
        history must never be orphaned by a room rename. Persisted through
        the standard atomic model.json write.
        """
        if not old or not new or old == new:
            return False
        m = self.model.pop(old, None)
        if m is None:
            return False
        self.model[new] = m
        if self.hass is not None and hasattr(self.hass, "async_create_task"):
            self.hass.async_create_task(
                self.hass.async_add_executor_job(self._persist_model_sync)
            )
        else:
            self._persist_model_sync()
        _LOGGER.info("Learner: room model migrated %r -> %r", old, new)
        return True

    def forget_room(self, name: str) -> None:
        """Drop a removed room's model key (persisted through the standard
        atomic write) — re-adding the name must start fresh."""
        if name in self.model:
            self.model.pop(name, None)
            if self.hass is not None and hasattr(self.hass, "async_create_task"):
                self.hass.async_create_task(
                    self.hass.async_add_executor_job(self._persist_model_sync)
                )
            else:
                self._persist_model_sync()
            _LOGGER.info("Learner: room model forgotten %r", name)

    def _persist_model_sync(self) -> None:
        """Atomically write the CURRENT model state to model.json."""
        assert self._dir is not None
        try:
            if not self.model:
                return
            blob = {
                "version": 1,
                "trained_at": self.trained_at
                or datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "rooms": self.model,
            }
            path = self._dir / MODEL_FILE
            tmp = path.with_suffix(f".tmp{uuid.uuid4().hex}")
            tmp.write_text(json.dumps(blob), encoding="utf-8")
            tmp.replace(path)
        except Exception:  # noqa: BLE001 - never break heating over logs
            _LOGGER.debug("Learner: model persist failed", exc_info=True)

    def _train_sync(self) -> None:
        """Executor-side heavy lifting: stream corpus → fit → save."""
        assert self._dir is not None
        try:
            model, coverage = self._fit_all()
            # Versioning + rollback: a room's fresh fit replaces the stored
            # one only when it is not WORSE (same 10-minute scale). Rooms
            # from a different scale (e.g. pre-windowing training) always
            # get replaced — their numbers are not comparable.
            prev = dict(self.model or {})
            kept_prev = replaced = scale_change = 0
            merged: dict[str, Any] = {}
            for name, m in (model or {}).items():
                old = prev.get(name)
                if old and old.get("scale_s") == m.get("scale_s"):
                    if (m.get("rmse") or 99.0) <= (old.get("rmse") or 99.0):
                        merged[name] = m
                        replaced += 1
                    else:
                        merged[name] = old   # rollback: previous was better
                        kept_prev += 1
                else:
                    merged[name] = m
                    if old:
                        scale_change += 1
            for name, old in prev.items():
                if name not in merged:
                    merged[name] = old
                    kept_prev += 1
            model = merged
            known = getattr(self, "known_rooms", None)
            if known is not None and isinstance(known, (set, list, tuple)):
                ghosts = sorted(set(model) - set(known))
                for g in ghosts:
                    del model[g]
                if ghosts:
                    coverage["dropped_ghosts"] = ghosts
            coverage = {**(coverage or {}), "kept_prev": kept_prev,
                        "replaced": replaced, "scale_change": scale_change}
            # sanity: never write an empty/garbage model
            if not model:
                self.last_error = "no room had enough data"
                _LOGGER.info("Learner: no room reached the coverage gates yet")
                return
            blob = {
                "version": 1,
                "trained_at": datetime.now(timezone.utc).isoformat(
                    timespec="seconds"
                ),
                "coverage": coverage,
                "rooms": model,
            }
            path = self._dir / MODEL_FILE
            tmp = path.with_suffix(f".tmp{uuid.uuid4().hex}")
            tmp.write_text(json.dumps(blob), encoding="utf-8")
            tmp.replace(path)
            self.model = model
            self.trained_at = blob["trained_at"]
            self.last_error = None
            _LOGGER.info(
                "Learner: trained models for %d room(s) (%s)",
                len(model), ", ".join(sorted(model)),
            )
        except Exception as err:  # noqa: BLE001 - training must never break
            self.last_error = str(err) or "unknown error"
            _LOGGER.warning("Learner: training failed: %s", self.last_error,
                            exc_info=True)
        finally:
            self.training = False

    def _fit_all(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """Stream every month-file once, building per-room regressions."""
        assert self._dir is not None
        files = sorted(self._dir.glob("data-*.jsonl"))
        if not files:
            return {}, {}
        days: set[str] = set()
        outdoor_seen: list[float] = []
        # per-room rolling history:
        # [(ts, temp, demand, outdoor|None, ch_on), …]
        hist: dict[str, list[tuple[float, float, float, float | None, bool]]] = {}
        xs: dict[str, list[list[float]]] = {}
        ys: dict[str, list[float]] = {}
        # per-room weights, index-aligned with xs/ys (they were misaligned
        # against demand-only lists when outdoor data was intermittent)
        xw: dict[str, list[float]] = {}
        heat_rows: dict[str, int] = {}
        # demand-only windows (houses without an outdoor sensor)
        xs0_all: dict[str, list[tuple[float, float]]] = {}
        ys0_all: dict[str, list[float]] = {}
        for path in files:
            if path.stat().st_size > 200 * 1024 * 1024:
                continue  # never read monster files whole
            try:
                with open(path, encoding="utf-8") as fh:
                    for line in fh:
                        if not line.strip():
                            continue
                        try:
                            row = json.loads(line)
                        except (ValueError, TypeError):
                            continue
                        self._absorb(
                            row, hist, xs, ys, heat_rows, days, outdoor_seen,
                            xs0_all, ys0_all, xw,
                        )
                        if sum(len(v) for v in xs.values()) > MAX_ROWS:
                            break
            except OSError:
                continue

        def spread(values: list[float]) -> float:
            return (max(values) - min(values)) if values else 0.0

        out_spread = spread(outdoor_seen)
        coverage = {
            "days": len(days),
            "outdoor_spread": round(out_spread, 1),
            "outdoor_available": bool(outdoor_seen),
            "heat_rows": {k: v for k, v in heat_rows.items() if v},
        }
        if len(days) < MIN_DAYS:
            return {}, coverage
        # Outdoor is REQUIRED when the house provides it (its cooling signal
        # matters), optional when it does not — a house with no outdoor
        # sensor still deserves a demand-driven model.
        outdoor_ok = not outdoor_seen or out_spread >= MIN_OUTDOOR_SPREAD
        if not outdoor_ok:
            return {}, coverage

        rooms: dict[str, Any] = {}
        room_names = sorted(set(xs) | set(xs0_all))
        for name in room_names:
            xs_r = xs.get(name) or []
            n = len(ys.get(name) or [])
            if n < MIN_WINDOWS:
                # No-outdoor house: fall back to the demand-only pairs.
                xs0, ys0 = xs0_all.get(name) or [], ys0_all.get(name) or []
                if outdoor_seen or len(ys0) < MIN_WINDOWS:
                    continue
                coef, rmse, n = self._fit_room(xs0, ys0)
                if coef is None:
                    continue
                rooms[name] = {
                    "coef": coef,       # {'demand', 'bias'} — no gap term
                    "n": n, "rmse": rmse,
                    "mode": "demand_only",
                    "scale_s": WINDOW_S,
                }
                continue
            wts = (xw.get(name) or [])
            if len(wts) != n:
                wts = [1.0] * n
            try:
                coef = _solve_ols(xs_r, ys[name], len(xs_r[0]), weights=wts)
            except Exception:  # noqa: BLE001
                continue
            a, bgap, bias = coef[0], coef[1], coef[-1]
            rmse = 0.0
            tot_w = 0.0
            for xrow, y, w0 in zip(xs_r, ys[name], wts):
                p = a * xrow[0] + bgap * xrow[1] + bias
                rmse += w0 * (p - y) ** 2
                tot_w += w0
            rmse = (rmse / tot_w) ** 0.5 if tot_w > 0 else 0.0
            if not all(abs(v) < 50 for v in (a, bgap, bias)) or rmse > 5.0:
                continue  # absurd fit → refuse
            rooms[name] = {
                "coef": {
                    "demand": round(a, 6),
                    "gap": round(bgap, 6),
                    "bias": round(bias, 6),
                },
                "n": n,
                "rmse": round(rmse, 4),
                "mode": "full",
                "scale_s": WINDOW_S,
                "weighted": True,
            }
        # Demand-only fallback counts for rooms that DID reach the full
        # gate are unnecessary (they already have the better model).
        del xs0_all
        return rooms, coverage

    # ------------------------------------------------------------- shadow
    def shadow_compare(self, room, demand, gap, cur, now):
        """Compare this room's predicted ΔT against reality (debug only).

        Called ≤1/minute per room, rotating; two samples ~min apart give
        the actual ΔT. Returns a one-line report or None (first sample).
        """
        # NOTE: gap at consecutive samples is nearly identical; the stored
        # prediction stays valid for the pair.
        prev = self._shadow_state.get(room)
        self._shadow_state[room] = (
            now, cur, self.predict_delta(room, demand, gap)
        )
        if prev is None:
            return None
        prev_ts, prev_temp, prev_pred = prev
        dt = now - prev_ts
        # The model speaks per-10-minutes; normalise reality to the same
        # window when the revisit landed anywhere near that scale.
        if not (240 < dt < 1200) or prev_pred is None:
            return None
        actual = (cur - prev_temp) * (600.0 / dt)
        if abs(actual) > 5.0:
            return None
        # scorecard: model error vs the do-nothing baseline ("no change")
        sc = self._shadow_score.setdefault(
            room, {"n": 0, "model_sse": 0.0, "base_sse": 0.0}
        )
        sc["n"] += 1
        sc["model_sse"] += (prev_pred - actual) ** 2
        sc["base_sse"] += actual ** 2
        return (
            f"{room}: shadow ΔT/10min predicted {prev_pred:+.2f} °C vs "
            f"actual {actual:+.2f} °C over {dt:.0f}s"
        )

    def shadow_scores(self) -> dict[str, dict[str, float]]:
        """/10min RMSE per room for the model and the no-change baseline.

        skill = (baseline − model) / baseline: >0 means the model beats
        doing nothing, negative means it is currently worse. Samples are
        runtime-accumulated and reset on restart.
        """
        out = {}
        for room, sc in self._shadow_score.items():
            n = sc["n"]
            if n < 1:
                continue
            model_rmse = (sc["model_sse"] / n) ** 0.5
            base_rmse = (sc["base_sse"] / n) ** 0.5
            skill = ((base_rmse - model_rmse) / base_rmse) if base_rmse > 1e-9 else 0.0
            out[room] = {
                "n": n,
                "model_rmse": round(model_rmse, 4),
                "baseline_rmse": round(base_rmse, 4),
                "skill": round(max(-1.0, min(1.0, skill)), 3),
            }
        return out

    # ------------------------------------------------------------- absorber
    def _absorb(self, row, hist, xs, ys, heat_rows, days, outdoor_seen,
                xs0_all, ys0_all, xw):
        """One corpus row → ~10-minute training windows.

        A 1-minute ΔT is mostly sensor noise; a 10-minute window carries
        real heating/cooling signal. Features are averaged over the window
        (demand) and anchored at its start (gap); the target is the
        temperature change across it.
        """
        ts = row.get("ts")
        try:
            t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except (ValueError, TypeError, AttributeError):
            return
        t_s = t.timestamp()
        days.add(t_s // 86400)
        outdoor = row.get("outdoor")
        outdoor_ok = isinstance(outdoor, (int, float)) and -60 < outdoor < 60
        if outdoor_ok:
            outdoor_seen.append(float(outdoor))
        boiler = row.get("boiler") or {}
        ch_on = bool(row.get("ch_on") or boiler.get("flame"))
        for zr in row.get("zones") or []:
            if not isinstance(zr, dict):
                continue
            name = zr.get("name")
            temp = zr.get("temp")
            if not isinstance(name, str) or not isinstance(temp, (int, float)):
                continue
            if zr.get("window_open") or zr.get("preheat"):
                continue  # these states would poison the dynamics
            demand = zr.get("demand")
            if not isinstance(demand, (int, float)):
                continue
            demand = min(1.0, max(0.0, float(demand)))
            if ch_on and demand > 0.05:
                heat_rows[name] = heat_rows.get(name, 0) + 1

            h = hist.setdefault(name, [])
            # pair against the sample ~WINDOW_S ago
            partner = None
            for (ts0, temp0, dem0, out0, ch0) in reversed(h):
                dt = t_s - ts0
                if WINDOW_S - WINDOW_TOL_S <= dt <= WINDOW_S + WINDOW_TOL_S:
                    partner = (ts0, temp0, dem0, out0)
                    break
                if dt > WINDOW_S + WINDOW_TOL_S:
                    break
            # append AFTER pairing so the current sample isn't its own partner
            h.append((t_s, float(temp), demand,
                      float(outdoor) if outdoor_ok else None,
                      bool(ch_on)))
            # prune anything older than the pairing horizon
            cutoff = t_s - (WINDOW_S + WINDOW_TOL_S)
            while h and h[0][0] < cutoff:
                h.pop(0)
            if partner is None:
                continue
            ts0, temp0, dem0, out0 = partner
            # average demand across the stored window samples
            win = [d for (s, _, d, _, _) in h if ts0 <= s <= t_s]
            avg_demand = sum(win) / len(win) if win else demand
            # heating weight: fraction of the window that ran the boiler,
            # floored at 0.25 so idle dynamics still contribute a little
            ch_win = [c for (s, _, _, _, c) in h if ts0 <= s <= t_s]
            ch_share = (sum(1 for c in ch_win if c) / len(ch_win)) if ch_win else 0.0
            w = 0.25 + 0.75 * ch_share
            y = float(temp) - temp0
            ys0_all.setdefault(name, []).append(y)
            xs0_all.setdefault(name, []).append((avg_demand, float(temp0), w))
            if not (outdoor_ok and out0 is not None):
                continue
            # gap anchored at the window START (the state being explained)
            gap = float(outdoor) - temp0
            xs.setdefault(name, []).append([avg_demand, gap])
            ys.setdefault(name, []).append(y)
            xw.setdefault(name, []).append(w)

    @staticmethod
    def _fit_room(demand_rows, target_deltas):
        """Demand-only weighted OLS per room: ΔT ≈ a·demand + bias.

        demand_rows are (avg_demand, start_temp, weight) triples from the
        window absorber — only the first element is the feature.
        Returns (coef_dict|None, rmse, n).
        """
        n = len(target_deltas)
        if n < 2 or len(demand_rows) != n:
            return None, 0.0, 0
        wts = [row[2] for row in demand_rows]
        try:
            coef = _solve_ols(
                [[row[0]] for row in demand_rows], target_deltas, 1, weights=wts
            )
        except Exception:  # noqa: BLE001
            return None, 0.0, 0
        a, bias = coef[0], coef[1]
        rmse = 0.0
        tot_w = 0.0
        for (d, _, w), y in zip(demand_rows, target_deltas):
            rmse += w * (a * d + bias - y) ** 2
            tot_w += w
        rmse = (rmse / tot_w) ** 0.5 if tot_w > 0 else 0.0
        if abs(a) >= 50 or abs(bias) >= 50 or rmse > 5.0:
            return None, 0.0, 0
        return (
            {"demand": round(a, 6), "bias": round(bias, 6)},
            round(rmse, 4),
            n,
        )
