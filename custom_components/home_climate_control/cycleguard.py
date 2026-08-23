"""Burner cycle minimizer (CycleGuard).

Every burner start costs gas: purge air sweeps the heat exchanger into the
flue, and short runs burn at poor efficiency while the boiler itself
warms up. A heating system that toggles CH on/off many times per hour is
wasting fuel even when every room feels fine.

This module watches actual CH state transitions over a rolling hour and:

  * refuses to *restart* the burner while it rests less than
    ``base_min_off * multiplier`` seconds (the rest window stretches
    automatically as cycling intensifies),
  * refuses to *stop* a burner that started less than ``hard_min_on``
    seconds ago (sub-4-minute burns are the worst offenders),
  * relaxes back toward the base rest window once cycling quiets down.

The multiplier is deliberately slow-moving (5% per evaluation) so one
odd morning never dominates.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any

# Tuning knobs (seconds / counts).
WINDOW_S = 3600.0            # rolling analysis window
TARGET_STARTS_PER_HOUR = 3.0 # comfortable cadence for a modulating boiler
HARD_MIN_ON_S = 240.0        # never allow burns shorter than this
BASE_MIN_OFF_S = 300.0       # rest window at multiplier 1.0
MULT_MAX = 3.0               # rest window can stretch to 15 min
SMOOTHING = 0.05             # multiplier approach speed per decision


class CycleGuard:
    """Adaptive min-on/min-off enforcement around CH enable/disable."""

    def __init__(
        self,
        *,
        target_per_hour: float = TARGET_STARTS_PER_HOUR,
        hard_min_on_s: float = HARD_MIN_ON_S,
        base_min_off_s: float = BASE_MIN_OFF_S,
        mult_max: float = MULT_MAX,
    ) -> None:
        self.target_per_hour = target_per_hour
        self.hard_min_on_s = hard_min_on_s
        self.base_min_off_s = base_min_off_s
        self.mult_max = mult_max

        self.mult = 1.0
        self.state = "idle"          # idle | on | resting
        self.last_reason = ""
        self._events: deque[tuple[float, bool]] = deque()

    # ----------------------------------------------------------------- utils
    def _prune(self, now: float) -> None:
        while self._events and now - self._events[0][0] > WINDOW_S:
            self._events.popleft()

    def starts_last_hour(self, now: float | None = None) -> int:
        now = time.monotonic() if now is None else now
        self._prune(now)
        return sum(1 for _, on in self._events if on)

    def _last(self, want_on: bool, now: float) -> float | None:
        self._prune(now)
        hits = [t for t, on in self._events if on == want_on]
        return max(hits) if hits else None

    def record(self, ch_enabled: bool, now: float | None = None) -> None:
        """Log an applied CH transition (call only on real changes)."""
        now = time.monotonic() if now is None else now
        self._events.append((now, bool(ch_enabled)))
        self.state = "on" if ch_enabled else "resting"

    # ---------------------------------------------------------------- policy
    def decide(
        self, want_on: bool, currently_on: bool, now: float | None = None
    ) -> tuple[bool, str]:
        """Return the CH state we should be in right now, plus why."""
        now = time.monotonic() if now is None else now

        # Adapt the rest-window multiplier from observed cycling rate.
        rate = self.starts_last_hour(now)
        target_mult = min(
            self.mult_max,
            max(1.0, rate / self.target_per_hour if rate else 1.0),
        )
        self.mult += SMOOTHING * (target_mult - self.mult)

        if want_on == currently_on:
            return currently_on, "no change"

        if want_on:  # requested START
            last_stop = self._last(False, now)
            need_rest = self.base_min_off_s * self.mult
            if last_stop is not None and (now - last_stop) < need_rest:
                remaining = int(need_rest - (now - last_stop))
                self.last_reason = f"resting ({remaining}s left)"
                return False, self.last_reason
            return True, "start"

        # requested STOP
        last_start = self._last(True, now)
        if last_start is not None and (now - last_start) < self.hard_min_on_s:
            remaining = int(self.hard_min_on_s - (now - last_start))
            self.last_reason = f"min-on floor ({remaining}s left)"
            return True, self.last_reason
        return False, "stop"

    def as_dict(self) -> dict[str, Any]:
        return {
            "starts_1h": self.starts_last_hour(),
            "multiplier": round(self.mult, 2),
            "state": self.state,
            "last_reason": self.last_reason,
        }
