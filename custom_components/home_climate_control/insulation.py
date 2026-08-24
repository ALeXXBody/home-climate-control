"""Per-room insulation score — how fast a room sheds heat, weather-aware.

A room falling 1 °C per hour sounds alarming until you notice it is -8 °C
outside; the same room losing 1 °C/h on a mild day would be scandalous.
Raw cool-down slopes conflate two things this score separates:

    loss factor  k  =  cool-down rate (°C/h)  /  (T_in - T_out)

k reads as "fraction of the indoor-outdoor gap surrendered every hour".
It is effectively UA/C for the room: driven by glazing, wall quality,
drafts and door habits, independent of how cold it happens to be outside.

Where the data comes from: the smart-setback learner already detects
genuine cool-down stretches (away/eco periods — long, quiet, heater-off).
While such a stretch is active the zone entity forwards samples here along
with the boiler's outdoor reading; each consecutive pair inside one
stretch yields an instantaneous k, EMA-smoothed into a persisted estimate.

Scores are mapped to plain-language labels:

    excellent   holds heat exceptionally well
    good        solid envelope, no action needed
    fair        noticeable losses — curtains, seals and habits pay off
    poor        leaks like a sieve — insulation work has real ROI

Pure logic apart from optional Store persistence, fully unit-testable.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = "home_climate_control_insulation"
STORAGE_VERSION = 1

PAIR_MIN_S = 20 * 60        # shorter gaps are too noisy for a slope
PAIR_MAX_S = 45 * 60        # longer gaps risk untracked disturbances
PAIR_MIN_DROP_C = 0.10      # smaller falls are sensor jitter, not physics
DENOM_MIN_K = 1.0           # never divide by a tiny ΔT
EMA_ALPHA = 0.20            # smoothing for per-room loss factors
K_MIN, K_MAX = 0.005, 0.60  # sanity clamp (fraction of ΔT per hour)

# Label thresholds on k (loss factor per hour).
LABELS: list[tuple[float, str]] = [
    (0.04, "excellent"),
    (0.08, "good"),
    (0.14, "fair"),
]


def label_for(k: float) -> str:
    for limit, name in LABELS:
        if k < limit:
            return name
    return "poor"


class _RoomState:
    __slots__ = ("last_ts", "last_temp", "active", "k_ema")

    def __init__(self) -> None:
        self.last_ts: float | None = None
        self.last_temp: float | None = None
        self.active = False     # inside a qualifying cool-down stretch?
        self.k_ema: float | None = None


class InsulationScorer:
    """Accumulates weather-normalized loss factors per room."""

    def __init__(self, hass, *, enabled: bool = True) -> None:
        self.hass = hass
        self.enabled = enabled
        self.rooms: dict[str, _RoomState] = {}
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY) if hass else None

    # ------------------------------------------------------------------ I/O
    async def async_load(self) -> None:
        if self._store is None:
            return
        try:
            data = await self._store.async_load() or {}
        except Exception:  # noqa: BLE001
            data = {}
        for name, r in data.items():
            v = r.get("k")
            if isinstance(v, (int, float)):
                st = self._room(name)
                st.k_ema = float(v)
                st.active = False
        if data:
            _LOGGER.info("Insulation scores restored for %d room(s)", len(data))

    def _persist(self) -> None:
        if self._store is None:
            return
        payload = {
            name: {"k": st.k_ema}
            for name, st in self.rooms.items()
            if st.k_ema is not None
        }

        async def _save() -> None:
            try:
                await self._store.async_save(payload)
            except Exception:  # noqa: BLE001
                _LOGGER.debug("insulation persist failed", exc_info=True)

        if self.hass is not None and hasattr(self.hass, "async_create_task"):
            self.hass.async_create_task(_save())
        else:
            import asyncio

            try:
                asyncio.get_running_loop()
            except RuntimeError:
                asyncio.run(_save())
            else:
                asyncio.ensure_future(_save())

    # --------------------------------------------------------------- scoring
    def _room(self, zone: str) -> _RoomState:
        return self.rooms.setdefault(zone, _RoomState())

    def observe(
        self,
        zone: str,
        ts: float,
        temp: float,
        outdoor: float | None,
        *,
        cooling: bool,
    ) -> float | None:
        """Feed one sample; returns the freshly-updated k estimate or None.

        ``cooling`` marks the room as being in a genuine heater-off stretch
        (the setback learner's cooling phase is the canonical source).
        Samples outside such stretches close any open stretch untouched.
        """
        st = self._room(zone)
        if not self.enabled or temp is None:
            return None

        if not cooling or outdoor is None:
            # Stretch broken: forget the anchor, keep the accumulated score.
            st.active = False
            st.last_ts = st.last_temp = None
            return None

        if not st.active or st.last_ts is None:
            st.active = True
            st.last_ts, st.last_temp = ts, temp
            return None

        span = ts - st.last_ts
        drop = st.last_temp - temp
        if span < PAIR_MIN_S or span > PAIR_MAX_S or drop < PAIR_MIN_DROP_C:
            # Not a usable pair; slide the anchor forward.
            st.last_ts, st.last_temp = ts, temp
            return None

        denom = max(DENOM_MIN_K, temp - outdoor)
        k_i = (drop / (span / 3600.0)) / denom
        k_i = max(K_MIN, min(K_MAX, k_i))
        st.k_ema = k_i if st.k_ema is None else st.k_ema + EMA_ALPHA * (k_i - st.k_ema)
        st.last_ts, st.last_temp = ts, temp
        self._persist()
        _LOGGER.debug("'%s' insulation k=%.4f (%s)", zone, st.k_ema, label_for(st.k_ema))
        return st.k_ema

    # ---------------------------------------------------------------- output
    def score_for(self, zone: str) -> tuple[str, float] | None:
        """(label, k) for a room, or None before enough data exists."""
        st = self.rooms.get(zone)
        if st is None or st.k_ema is None:
            return None
        return label_for(st.k_ema), st.k_ema

    def as_dict(self) -> dict[str, Any]:
        rooms = {}
        for name, st in sorted(self.rooms.items()):
            entry: dict[str, Any] = {"label": None, "k": None}
            if st.k_ema is not None:
                entry["label"] = label_for(st.k_ema)
                entry["k"] = round(st.k_ema, 4)
            rooms[name] = entry
        return {"enabled": self.enabled, "rooms": rooms}


if __name__ == "__main__":  # pragma: no cover - manual sanity run
    s = InsulationScorer(None)
    t0 = time.time()
    tin, tout = 20.0, -5.0
    # 25 K gap, losing 1 °C/h  ->  k = 0.04  ->  good/excellent boundary
    t = t0
    for i in range(6):
        t += 22 * 60
        tin -= 1.0 * (22 / 60.0)
        s.observe("Salon", t, tin, tout, cooling=True)
    print(s.as_dict())
