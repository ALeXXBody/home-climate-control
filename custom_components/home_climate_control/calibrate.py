"""Bootstrap heat-rate calibration — measure a room's °C/h on demand.

The setback learner (setback.py) discovers each room's warm-up speed only
opportunely: after real setback→recovery cycles happen by themselves.
A freshly configured installation has no history, so smart offsets stay
disabled for days or weeks.

Calibration short-circuits that wait. When the user starts a session for a
room, the controller raises that room's target a couple of degrees; while
the radiator does its work we simply time the temperature climb:

    rate (°C/h) = temperature gained / hours elapsed

The measurement ends when the room gained TARGET_GAIN_C (default 1.5 °C),
when MAX_SESSION_S elapsed (partial result if usable), or when cancelled.
The resulting rate is injected into the setback learner as its first
sample, so learned behaviour starts from measurement instead of zero.

Pure logic module: no Home Assistant imports, fully unit-testable. The
caller (central controller) owns setpoint changes and persistence.
"""

from __future__ import annotations

import logging
import time
from typing import Any

_LOGGER = logging.getLogger(__name__)

TARGET_GAIN_C = 1.5          # finish once the room climbed this much
MIN_SPAN_S = 15 * 60         # shorter spans are noise -> discard
MAX_SESSION_S = 90 * 60      # hard timeout for the whole session
RATE_MIN_CPH = 0.2           # sanity clamps, same envelope setback uses
RATE_MAX_CPH = 12.0


class RoomCalibrator:
    """Tracks at most one bootstrap calibration session at a time."""

    def __init__(self) -> None:
        self._zone: str | None = None
        self._t0: float | None = None
        self._temp0: float | None = None
        self._last_temp: float | None = None
        self._result: dict[str, Any] | None = None

    def _elapsed(self, ts: float) -> float:
        """Seconds since the session baseline; 0 when unanchored."""
        return ts - self._t0 if self._t0 is not None else 0.0

    # ---------------------------------------------------------------- state
    @property
    def active_zone(self) -> str | None:
        """Zone currently being calibrated, if any."""
        return self._zone

    def active(self) -> bool:
        return self._zone is not None

    # --------------------------------------------------------------- control
    def start(self, zone: str, ts: float | None = None, temp: float | None = None) -> dict[str, Any]:
        """Begin measuring *zone*. Returns the session descriptor."""
        if self.active():
            raise ValueError(f"calibration already running for '{self._zone}'")
        ts = ts if ts is not None else time.time()
        self._zone = zone
        self._t0 = ts
        self._temp0 = temp
        self._result = None
        _LOGGER.info("Calibration started for '%s' (start temp %s)", zone, temp)
        return {"zone": zone, "started": ts, "status": "measuring"}

    def observe(self, zone: str, ts: float, temp: float) -> dict[str, Any] | None:
        """Feed one temperature sample.

        Returns the final result dict exactly once when the session ends
        (target reached), otherwise None. Samples from other rooms are
        ignored.
        """
        if not self.active() or zone != self._zone or temp is None:
            return None
        self._last_temp = temp
        if self._temp0 is None:
            # First sample of the session anchors the baseline.
            self._t0 = ts
            self._temp0 = temp
            return None
        span = self._elapsed(ts)
        gained = temp - self._temp0
        if gained >= TARGET_GAIN_C and span >= MIN_SPAN_S:
            return self._finish("done", span, gained)
        if span >= MAX_SESSION_S:
            return self._expire(ts)
        return None

    def cancel(self, ts: float | None = None) -> dict[str, Any]:
        """User aborted; no rate is reported."""
        ts = ts if ts is not None else time.time()
        if not self.active():
            return {"status": "idle"}
        zone = self._zone
        self._reset()
        res = {"zone": zone, "status": "cancelled"}
        _LOGGER.info("Calibration cancelled for '%s'", zone)
        return res

    def maybe_expire(self, ts: float) -> dict[str, Any] | None:
        """Timeout check driven by the control loop tick."""
        if not self.active():
            return None
        span = self._elapsed(ts)
        if span >= MAX_SESSION_S:
            return self._expire(ts)
        return None

    # --------------------------------------------------------------- helpers
    def _expire(self, ts: float) -> dict[str, Any] | None:
        return self.finish_partial(self._last_temp, ts=ts)

    def finish_partial(
        self, last_temp: float | None, ts: float | None = None, span: float | None = None
    ) -> dict[str, Any] | None:
        """Close the session with whatever the data supports.

        A partial session yields a rate only if it ran long enough to be
        meaningful (>= MIN_SPAN_S); otherwise it reports failure.
        """
        if not self.active():
            return None
        ts = ts if ts is not None else time.time()
        if span is None:
            span = self._elapsed(ts)
        gained = (
            (last_temp - self._temp0)
            if (last_temp is not None and self._temp0 is not None)
            else 0.0
        )
        if span >= MIN_SPAN_S and gained > 0.05:
            return self._finish("partial", span, gained)
        zone = self._zone
        self._reset()
        _LOGGER.info("Calibration for '%s' failed: %.0f s span, gain %.2f C", zone, span, gained)
        return {"zone": zone, "status": "failed", "minutes": round(span / 60.0, 1)}

    def _finish(self, status: str, span: float, gained: float) -> dict[str, Any]:
        hours = span / 3600.0
        rate = max(RATE_MIN_CPH, min(RATE_MAX_CPH, gained / hours))
        zone = self._zone
        self._reset()
        _LOGGER.info("Calibration for '%s': %.2f °C/h (%.2f °C in %.0f min)", zone, rate, gained, span / 60.0)
        return {
            "zone": zone,
            "status": status,
            "rate_cph": round(rate, 2),
            "gain_c": round(gained, 2),
            "minutes": round(span / 60.0, 1),
        }

    def _reset(self) -> None:
        self._zone = None
        self._t0 = None
        self._temp0 = None
        self._last_temp = None

    def as_dict(self) -> dict[str, Any]:
        """Status snapshot for diagnostics / panel."""
        return {
            "active": self.active(),
            "zone": self._zone,
            "started": self._t0,
            "baseline_temp": self._temp0,
        }
