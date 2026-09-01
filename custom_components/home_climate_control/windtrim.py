"""Wind trimming for the outdoor temperature the heating curve uses.

Wind raises building heat loss through infiltration. Commercial weather
compensators (e.g. NBE) ship a "chill factor" for exactly this, and the
HA-community CompCurve formula adds ``0.25 × wind^0.9`` to the flow target.
We apply the equivalent as a *bounded trim on the outdoor temperature the
curve sees*, so the existing curve / auto-tune math stays untouched:

    trim_c = min(max_delta, 0.25 * wind_kmh ** 0.9)
    effective_outdoor = outdoor - trim_c

Benefits are systemic, not just comfort: windy-day cold rooms no longer
push the auto-tuner to inflate the curve coefficient globally (which
overshoots on calm days), so the learned coefficient settles lower and
steadier. Raw outdoor stays untouched for display and logging.

NOT a weather-app "feels like": skin wind-chill would push the curve far
past what the building actually loses. Bounded, off by default.
"""

from __future__ import annotations

import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)

WIND_COEFF = 0.25
WIND_EXP = 0.9


def wind_trim_c(wind_kmh: float | None, max_delta: float) -> float:
    """Trim (°C-equivalent) for a wind speed, clamped at ``max_delta``."""
    if wind_kmh is None or wind_kmh < 0:
        return 0.0
    return min(max(max_delta, 0.0), WIND_COEFF * (wind_kmh ** WIND_EXP))


class WindTrimmer:
    """Reads ``wind_speed`` from a HA weather entity; trims curve outdoor."""

    def __init__(
        self,
        hass: Any,
        entity: str | None,
        enabled: bool = False,
        max_delta: float = 3.0,
    ) -> None:
        self.hass = hass
        self.entity = (entity or "").strip() or None
        self.enabled = bool(enabled)
        self.max_delta = max(0.0, float(max_delta))

        self.wind_kmh: float | None = None
        self.trim_c: float = 0.0

    def refresh(self) -> None:
        """Re-read wind speed from the configured weather entity (if any).

        ``wind_speed`` is converted to km/h from whatever unit the weather
        integration reports (``wind_speed_unit``): m/s, mph, ft/s — some
        integrations are configured in units other than HA's km/h default.
        """
        self.wind_kmh = None
        self.trim_c = 0.0
        if not self.enabled or not self.entity or self.hass is None:
            return
        states = getattr(self.hass, "states", None)
        if states is None:
            return
        st = states.get(self.entity)
        if st is None or st.state in ("unknown", "unavailable", ""):
            return
        raw = st.attributes.get("wind_speed")
        if raw is None:
            return
        try:
            val = float(str(raw).split()[0])
        except (TypeError, ValueError, IndexError):
            return
        if val < 0:
            return
        unit = (st.attributes.get("wind_speed_unit") or "km/h").strip().lower()
        conv = {
            "km/h": 1.0, "kph": 1.0, "kmh": 1.0,
            "m/s": 3.6, "ms": 3.6,
            "mph": 1.609344,
            "ft/s": 1.09728, "fts": 1.09728,
        }.get(unit, 1.0)
        kmh = val * conv
        self.wind_kmh = round(kmh, 1)
        self.trim_c = round(wind_trim_c(kmh, self.max_delta), 1)

    def effective(self, outdoor: float | None) -> float | None:
        """Outdoor with the wind trim applied (``None`` passes through)."""
        if outdoor is None:
            return None
        return round(outdoor - self.trim_c, 1)

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "entity": self.entity,
            "wind_kmh": self.wind_kmh,
            "trim_c": self.trim_c,
            "max_delta_c": self.max_delta,
        }
