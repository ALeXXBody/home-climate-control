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
MIN_ROOM_ROWS = 2_000     # heat-relevant rows (demand > 0 / CH on) per room
MIN_OUTDOOR_SPREAD = 8.0  # °C; mild-only weeks must not set the model


def _solve_ols(xs: list[list[float]], ys: list[float], k: int) -> list[float]:
    """Closed-form small ridge OLS: returns k+1 coefficients (last = bias)."""
    m = k + 1
    a = [[0.0] * m for _ in range(m)]
    b = [0.0] * m
    for row, y in zip(xs, ys):
        feat = [*row, 1.0]
        for i in range(m):
            xi = feat[i]
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
        # rotating debug of one prediction-vs-actual per tick
        self._shadow_state: dict[str, Any] = {}

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
        """Predict next-minute ΔT (°C) for a room; None when not modeled."""
        m = self.model.get(room)
        if not isinstance(m, dict):
            return None
        try:
            coef = m["coef"]
            a = float(coef["demand"])
            bgap = float(coef["gap"])
            c = float(coef["bias"])
        except (KeyError, TypeError, ValueError):
            return None
        if not all(isinstance(v, (int, float)) for v in (a, bgap, c)):
            return None
        return a * demand + bgap * gap + c

    # ------------------------------------------------------------ retraining
    def maybe_train(self, now: float | None = None) -> bool:
        """Cheap tick check: dispatch a retrain when the week is due."""
        if now is None:
            now = time.time()
        if self.training or self._dir is None:
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
            return False
        self.last_attempt = now
        self.training = True
        self.hass.async_add_executor_job(self._train_sync)
        return True

    def _train_sync(self) -> None:
        """Executor-side heavy lifting: stream corpus → fit → save."""
        assert self._dir is not None
        try:
            model, coverage = self._fit_all()
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
        # pending: room -> (prev_ts_seconds, prev_temp)
        prev: dict[str, tuple[float, float]] = {}
        xs: dict[str, list[list[float]]] = {}
        ys: dict[str, list[float]] = {}
        heat_rows: dict[str, int] = {}
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
                            row, prev, xs, ys, heat_rows, days, outdoor_seen
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
            "heat_rows": {k: v for k, v in heat_rows.items() if v},
        }
        if len(days) < MIN_DAYS or out_spread < MIN_OUTDOOR_SPREAD:
            return {}, coverage

        rooms: dict[str, Any] = {}
        for name, xs_r in xs.items():
            n = len(ys[name])
            if n < MIN_ROOM_ROWS:
                continue
            try:
                coef = _solve_ols(xs_r, ys[name], len(xs_r[0]))
            except Exception:  # noqa: BLE001
                continue
            a, bgap, bias = coef[0], coef[1], coef[-1]
            rmse = 0.0
            for xrow, y in zip(xs_r, ys[name]):
                p = a * xrow[0] + bgap * xrow[1] + bias
                rmse += (p - y) ** 2
            rmse = (rmse / n) ** 0.5
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
            }
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
        if not (10 < dt < 600) or prev_pred is None:
            return None
        actual = cur - prev_temp
        if abs(actual) > 5.0:
            return None
        return (
            f"{room}: shadow ΔT predicted {prev_pred:+.2f} °C vs actual "
            f"{actual:+.2f} °C over {dt:.0f}s"
        )

    # ------------------------------------------------------------- absorber
    def _absorb(self, row, prev, xs, ys, heat_rows, days, outdoor_seen):
        """One corpus row → delta training pairs (linked to the previous)."""
        ts = row.get("ts")
        try:
            t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except (ValueError, TypeError, AttributeError):
            return
        t_s = t.timestamp()
        days.add(t_s // 86400)
        outdoor = row.get("outdoor")
        if isinstance(outdoor, (int, float)) and -60 < outdoor < 60:
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
            old = prev.get(name)
            prev[name] = (t_s, float(temp))
            if old is None:
                continue
            prev_ts, prev_temp = old
            dt = t_s - prev_ts
            if dt <= 15 or dt > 150:
                continue  # only true ~1-minute successive rows pair up
            # feature row: (demand, outdoor-gap); target: ΔT over the pair
            if not (isinstance(outdoor, (int, float)) and -60 < outdoor < 60):
                continue
            xs.setdefault(name, []).append(
                [demand, float(outdoor) - float(prev_temp)]
            )
            ys.setdefault(name, []).append(float(temp) - prev_temp)
