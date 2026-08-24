"""Open-window detection from the temperature slope — no contact sensors.

A window dumped open in winter is dramatic: the room sheds 0.5–2 °C within
minutes, far faster than structural cooling ever does (a typical leaky room
loses well under 2 °C per *hour*). That contrast is the whole trick:

    fast drop  -> window (or door to cold) almost certainly open
    slow drift -> just weather; keep heating normally

When a drop faster than WINDOW_DROP_C within WINDOW_LOOKBACK_S is seen,
the detector reports "open" and the zone pauses heat exactly as if a real
door sensor had tripped — same flag, same panel badge, same demand cut.

Recovery is slope-gated: after a minimum pause, the heat resumes as soon
as the temperature has stopped falling (measured against a ~5-minute-old
sample), or at a hard MAX_PAUSE_S cap so a stuck state can never silently
freeze a room.

Only used for rooms WITHOUT physical window/door sensors; where contact
sensors exist they are strictly better and take precedence.

Pure logic: no Home Assistant imports, fully unit-testable.
"""

from __future__ import annotations

import logging
import time
from typing import Any

_LOGGER = logging.getLogger(__name__)

WINDOW_DROP_C = 0.4        # drop over the lookback span that trips detection
WINDOW_LOOKBACK_S = 8 * 60 # ...within this many minutes
SAMPLE_MAX_GAP_S = 5 * 60  # older samples beyond this gap are stale, dropped
MIN_PAUSE_S = 10 * 60      # shortest possible pause after a trip
SLOPE_REF_S = 5 * 60       # slope measured against a sample this old
SLOPE_CLOSE_CPH = -0.15    # °C/h; gentler than this counts as "stopped falling"
MAX_PAUSE_S = 45 * 60      # hard cap on a slope-detected pause


class SlopeWindowDetector:
    """Per-room state machine fed with temperature samples."""

    def __init__(self) -> None:
        self.samples: list[tuple[float, float]] = []  # (ts, temp), ascending
        self.open = False
        self._opened_at: float | None = None
        self._min_seen: float | None = None   # lowest temp since opening
        self._last_drop_check: float | None = None

    # ------------------------------------------------------------------ feed
    def observe(self, ts: float, temp: float) -> bool:
        """Feed one sample; returns True while the room counts as 'open'."""
        if temp is None:
            return self.open

        # Drop stale history so long sensor outages can't fake a cliff.
        # While open we deliberately keep a longer tail: the recovery check
        # compares against samples several minutes old.
        keep = MIN_PAUSE_S + SLOPE_REF_S if self.open else SAMPLE_MAX_GAP_S
        self.samples = [(t, v) for (t, v) in self.samples if ts - t <= keep]
        self.samples.append((ts, temp))
        if len(self.samples) > 128:
            self.samples = self.samples[-128:]

        if not self.open:
            self._check_for_drop(ts)
        else:
            self._check_for_recovery(ts)
        return self.open

    # --------------------------------------------------------------- phases
    def _check_for_drop(self, ts: float) -> None:
        """Closed phase: hunt for an abnormally fast temperature fall."""
        ref_ts, ref_temp = self.samples[0]
        newest_ts, newest_temp = self.samples[-1]
        span = newest_ts - ref_ts
        if span < SAMPLE_MAX_GAP_S / 3:
            return  # need at least ~a couple minutes of context
        if newest_temp <= ref_temp - WINDOW_DROP_C:
            self._trip(ts, ref_temp, newest_temp)

    def _check_for_recovery(self, ts: float) -> None:
        """Open phase: close as soon as the fall has actually stopped.

        Strategy (same shape commercial TRVs use): enforce a minimum pause,
        then extend it only while the room is still measurably falling.
        Slope is measured against a sample ~SLOPE_REF_S old, so sensor
        jitter cannot end a pause and a slow bleed cannot hide in it.
        """
        assert self._opened_at is not None
        newest_ts, newest_temp = self.samples[-1]

        if newest_ts - self._opened_at < MIN_PAUSE_S:
            return

        # Reference sample: the one whose age is closest to SLOPE_REF_S.
        ref = None
        best = None
        for t, v in self.samples[:-1]:
            age = newest_ts - t
            if age < SLOPE_REF_S / 2:
                break
            score = abs(age - SLOPE_REF_S)
            if best is None or score < best:
                best, ref = score, (t, v)
        if ref is None:
            return
        hours = (newest_ts - ref[0]) / 3600.0
        slope_cph = (newest_temp - ref[1]) / hours
        if slope_cph >= SLOPE_CLOSE_CPH:
            _LOGGER.info("Temperature stabilised (%.2f °C/h) — window pause ends", slope_cph)
            self._close(ts)
            return
        if ts - self._opened_at >= MAX_PAUSE_S:
            _LOGGER.info("Slope-window pause hit %d min cap — clearing", MAX_PAUSE_S // 60)
            self._close(ts)

    def _trip(self, ts: float, ref_temp: float, now_temp: float) -> None:
        self.open = True
        self._opened_at = ts
        _LOGGER.info(
            "Fast temperature drop detected (%.1f → %.1f °C) — pausing heat",
            ref_temp,
            now_temp,
        )

    def _close(self, ts: float) -> None:
        self.open = False
        self._opened_at = None
        self._min_seen = None
        self.samples = self.samples[-2:]  # re-arm on recent context only

    # ---------------------------------------------------------------- output
    def as_dict(self) -> dict[str, Any]:
        return {
            "active": self.open,
            "since": self._opened_at,
            "samples": len(self.samples),
        }


if __name__ == "__main__":  # pragma: no cover - manual sanity run
    d = SlopeWindowDetector()
    t0 = time.time()
    for i in range(10):
        d.observe(t0 + i * 60, 21.0 - i * 0.08)  # gentle cooling
    print("slow drift ->", d.observe(t0 + 600, 20.4))
    print("fast dump  ->", d.observe(t0 + 660, 19.9))
