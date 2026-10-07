"""Solar-gain comfort trim (optional per-room extra).

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

# Sun-fallback (houses without a lux sensor): position-only proxy from HA's
# sun integration. Deliberately weaker than the measured-lux trim — the sun
# says nothing about clouds or shading, so a grey high-sun afternoon must
# not trim heating aggressively.
SUN_OFFSET_C = 0.3
SUN_HIGH_SIN = 0.55   # sin(elevation) ≈ elevation ≥ ~33°
SUN_LOW_SIN = 0.40    # ≈ ≥ 24° to keep, hysteresis between the two


def _sin_elev(elev: float) -> float:
    import math

    return max(0.0, min(1.0, math.sin(math.radians(elev))))


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
        # Sun-fallback state (used only when no lux sensor feeds updates)
        self.sun_ema: float | None = None
        self.sun_elev: float | None = None

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

    def update_sun(self, elevation: float | None) -> None:
        """Fallback detector from HA's sun integration (position only).

        Ignored whenever a lux sensor is reporting — measurement beats
        astronomy. The activation thresholds sit HIGH on the elevation
        curve and the comfort offset is smaller than the lux trim, so a
        cloudy high-sun day costs at most a mild under-trim.
        """
        if elevation is None:
            return
        try:
            elevation = float(elevation)
        except (TypeError, ValueError):
            return
        if not -90.0 <= elevation <= 90.0:
            return
        self.sun_elev = elevation
        if self.lux_ema is not None:
            return   # measured sunlight is available; sun proxy stays idle
        s = _sin_elev(elevation)
        self.sun_ema = (
            s if self.sun_ema is None
            else self.sun_ema * (1 - EMA_ALPHA) + s * EMA_ALPHA
        )
        if not self.active and self.sun_ema >= SUN_HIGH_SIN:
            self.active = True
        elif self.active and self.sun_ema <= SUN_LOW_SIN:
            self.active = False

    @property
    def offset_contribution(self) -> float:
        """Value to ADD to the preset offset (negative = lower target)."""
        if not self.active:
            return 0.0
        return -(self.offset_c if self.lux_ema is not None else SUN_OFFSET_C)

    def as_dict(self) -> dict:
        return {
            "active": self.active,
            "lux_ema": round(self.lux_ema, 0) if self.lux_ema is not None else None,
            "offset_c": self.offset_contribution,
            "source": "lux" if self.lux_ema is not None else "sun",
            "sun_elevation": (
                round(self.sun_elev, 1) if self.sun_elev is not None else None
            ),
        }
