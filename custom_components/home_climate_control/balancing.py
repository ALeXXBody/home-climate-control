"""TRV balancing assistance (Tier 4).

A per-room valve-position entity (many Zigbee/Wifi TRVs expose 0–100 %)
lets HCC build a rolling balance picture:

- ``undersupplied`` — valve mostly wide open yet the room stays below
  target: radiator undersized, blocked, or air-locked
- ``oversupplied``  — valve mostly closed while the room sits at/above
  target: radiator oversized for the room

Both are balancing actions for the user, not automatic ones — HCC
reports; you adjust lockshield valves.
"""

from __future__ import annotations

from collections import deque

WINDOW_SAMPLES = 120  # 60 s ticks → 2 h
MIN_SAMPLES = 12      # ~12 min before a verdict
OPEN_UNDERSUPPLIED = 85.0
CLOSED_OVERSUPPLIED = 15.0


class BalanceMonitor:
    """Rolling valve-position analysis for one room."""

    def __init__(self, window: int = WINDOW_SAMPLES) -> None:
        self._hist: deque[tuple[float, bool]] = deque(maxlen=window)

    def sample(self, valve_pct: float | None, below_target: bool) -> None:
        if valve_pct is None:
            return
        try:
            valve_pct = max(0.0, min(100.0, float(valve_pct)))
        except (TypeError, ValueError):
            return
        self._hist.append((valve_pct, bool(below_target)))

    def report(self) -> dict:
        n = len(self._hist)
        if n < MIN_SAMPLES:
            return {"state": "learning", "samples": n}
        avg_open = sum(v for v, _ in self._hist) / n
        below_share = sum(1 for _, b in self._hist if b) / n
        if avg_open >= OPEN_UNDERSUPPLIED and below_share > 0.5:
            state = "undersupplied"
        elif avg_open <= CLOSED_OVERSUPPLIED and below_share < 0.2:
            state = "oversupplied"
        else:
            state = "ok"
        return {
            "state": state,
            "avg_open_pct": round(avg_open, 1),
            "below_share": round(below_share, 2),
            "samples": n,
        }
