"""CO₂ air-quality watch (Tier 3).

A per-room CO₂ sensor drives a ``needs_ventilation`` flag with
hysteresis. HCC surfaces the flag (zone attribute + diagnostics) so HA
automations can open vents/notify — heating itself is **not** paused by
CO₂ alone (a stuffy room still needs heat); the existing window/slope
detection already pauses heat during real airing.

Thresholds follow common guidance: >1000 ppm is getting stuffy, <800 is
fresh.
"""

from __future__ import annotations

CO2_HIGH = 1100
CO2_LOW = 800


class Co2Guard:
    """Hysteresis CO₂ monitor for one room."""

    def __init__(self, high: int = CO2_HIGH, low: int = CO2_LOW) -> None:
        self.high = int(high)
        self.low = int(low)
        self.ppm: float | None = None
        self.needs_ventilation = False

    def update(self, ppm: float | None) -> None:
        if ppm is None:
            return
        try:
            ppm = float(ppm)
        except (TypeError, ValueError):
            return
        if ppm <= 0 or ppm > 10000:  # implausible
            return
        self.ppm = ppm
        if not self.needs_ventilation and self.ppm >= self.high:
            self.needs_ventilation = True
        elif self.needs_ventilation and self.ppm <= self.low:
            self.needs_ventilation = False

    def as_dict(self) -> dict:
        return {
            "ppm": round(self.ppm) if self.ppm is not None else None,
            "needs_ventilation": self.needs_ventilation,
        }
