"""Solar-gain comfort trim (Tier 3).

Direct sunlight makes occupants comfortable at a *lower* air temperature
(radiant warmth). A per-room lux sensor lets HCC shave a small comfort
offset off the effective setpoint while the sun is actually warming the
room — saving gas without losing comfort.

Debounced with an EMA + hysteresis so passing clouds do not flap the
heating on/off.
"""

from __future__ import annotations

# Direct-sun thresholds (lux). Indoor daylight ≈ 100–500; overcast ≈ 1000;
# a sunlit room is typically > 3000–5000.
LUX_HIGH = 5000
LUX_LOW = 1500
COMFORT_OFFSET_C = 0.5
EMA_ALPHA = 0.2


class SolarGain:
    """Hysteresis solar-gain detector for one room."""

    def __init__(
        self,
        lux_high: float = LUX_HIGH,
        lux_low: float = LUX_LOW,
        offset_c: float = COMFORT_OFFSET_C,
    ) -> None:
        self.lux_high = float(lux_high)
        self.lux_low = float(lux_low)
        self.offset_c = float(offset_c)
        self.lux_ema: float | None = None
        self.active = False

    def update(self, lux: float | None) -> None:
        if lux is None:
            return
        try:
            lux = float(lux)
        except (TypeError, ValueError):
            return
        if lux < 0:
            return
        self.lux_ema = (
            lux if self.lux_ema is None
            else self.lux_ema * (1 - EMA_ALPHA) + lux * EMA_ALPHA
        )
        if not self.active and self.lux_ema >= self.lux_high:
            self.active = True
        elif self.active and self.lux_ema <= self.lux_low:
            self.active = False

    @property
    def offset_contribution(self) -> float:
        """Value to ADD to the preset offset (negative = lower target)."""
        return -self.offset_c if self.active else 0.0

    def as_dict(self) -> dict:
        return {
            "active": self.active,
            "lux_ema": round(self.lux_ema, 0) if self.lux_ema is not None else None,
            "offset_c": self.offset_contribution,
        }
