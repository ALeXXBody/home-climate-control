"""Smart night/Away setbacks — learned per room, not fixed offsets.

Fixed preset offsets (away -4 °C etc.) ignore reality: a small room with
a hot radiator recovers 4 °C in 20 minutes (deep setback = big saving),
while a leaky hall may take three hours (deep setback = cold feet and a
brutal morning catch-up burn).

This learner measures each room's actual recovery speed every time it
comes out of a setback, then sizes that room's future setback depth so
recovery fits inside RECOVERY_TARGET_H:

    depth = recovery_rate(°C/h) × RECOVERY_TARGET_H   (clamped 1..5 °C)

Slow rooms converge to shallow setbacks; snappy rooms earn deep ones.
Fewer wasted catch-up burns + deeper savings where they are free.

Learning needs at least MIN_CYCLES completed setback→recovery cycles per
room; until then the classic fixed offsets apply. Everything persists
across restarts via the HA Store.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = "home_climate_control_setbacks"
STORAGE_VERSION = 1

SETBACK_PRESETS = ("away", "eco")
RECOVERY_TARGET_H = 1.0     # rooms must be back within ~1 h of leaving setback
RECOVERY_WATCH_S = 2 * 3600 # give up measuring after 2 h of recovery
MIN_CYCLES = 3              # completed cycles before offsets are trusted
LEARNED_MIN_C = -5.0        # deepest allowed learned offset
LEARNED_MAX_C = -1.0        # shallowest useful setback
EMA_ALPHA = 0.35            # smoothing for rate estimates
MIN_SEGMENT_S = 15 * 60     # segments shorter than this are noise


class _RoomState:
    __slots__ = (
        "phase", "seg_t0", "seg_temp0", "cool_ema", "warm_ema",
        "cycles", "rec_samples",
    )

    def __init__(self) -> None:
        self.phase = "comfort"      # comfort | setback | recover
        self.seg_t0: float | None = None
        self.seg_temp0: float | None = None
        self.cool_ema: float | None = None
        self.warm_ema: float | None = None
        self.cycles = 0
        self.rec_samples: list[tuple[float, float]] = []


class SetbackLearner:
    """Tracks per-room thermal behaviour around away/eco periods."""

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
            st = _RoomState()
            st.cool_ema = r.get("cool_ema")
            st.warm_ema = r.get("warm_ema")
            st.cycles = int(r.get("cycles", 0))
            self.rooms[name] = st
        if data:
            _LOGGER.info("Setback learner restored %d room(s)", len(data))

    def _persist(self) -> None:
        if self._store is None:
            return
        payload = {
            name: {
                "cool_ema": st.cool_ema,
                "warm_ema": st.warm_ema,
                "cycles": st.cycles,
            }
            for name, st in self.rooms.items()
            if st.cool_ema is not None or st.warm_ema is not None or st.cycles
        }

        async def _save() -> None:
            try:
                await self._store.async_save(payload)
            except Exception:  # noqa: BLE001
                _LOGGER.debug("setback persist failed", exc_info=True)

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

    # -------------------------------------------------------------- learning
    @staticmethod
    def _is_setback(preset: str | None) -> bool:
        return preset in SETBACK_PRESETS

    def _room(self, zone: str) -> _RoomState:
        return self.rooms.setdefault(zone, _RoomState())

    def observe(
        self,
        zone: str,
        ts: float,
        temp: float | None,
        preset: str | None,
        *,
        heating_allowed: bool = True,
    ) -> None:
        """Feed one temperature sample for a room.

        ts: unix seconds. heating_allowed False (window open / HVAC off)
        freezes learning — those temps describe physics we don't control.
        """
        if not self.enabled or temp is None:
            return
        st = self._room(zone)
        was = st.phase

        # ---- phase transitions on preset change --------------------------
        if self._is_setback(preset):
            if was != "setback":
                # entering setback: start a cooling segment
                st.phase = "setback"
                st.seg_t0, st.seg_temp0 = ts, temp
                st.rec_samples = []
            elif st.seg_t0 is not None:
                pass  # continue cooling segment
            return

        # preset is comfort/none/boost from here on
        if was == "setback":
            dur = ts - (st.seg_t0 or ts)
            if st.seg_temp0 is not None and dur >= MIN_SEGMENT_S:
                cool = (temp - st.seg_temp0) / (dur / 3600.0)  # °C/h (≤0)
                if st.cool_ema is None:
                    st.cool_ema = cool
                else:
                    st.cool_ema += EMA_ALPHA * (cool - st.cool_ema)
            st.phase = "recover"
            st.seg_t0, st.seg_temp0 = ts, temp
            st.rec_samples = [(ts, temp)]
            return

        if was == "recover":
            st.rec_samples.append((ts, temp))
            t0 = st.seg_t0 or ts
            span = ts - t0
            gained = temp - (st.seg_temp0 if st.seg_temp0 is not None else temp)
            done = gained >= 0.8 or span >= RECOVERY_WATCH_S
            if done and span >= MIN_SEGMENT_S:
                warm = gained / (span / 3600.0)
                warm = max(0.2, min(12.0, warm))  # sanity clamp °C/h
                if st.warm_ema is None:
                    st.warm_ema = warm
                else:
                    st.warm_ema += EMA_ALPHA * (warm - st.warm_ema)
                st.cycles += 1
                st.phase = "comfort"
                st.seg_t0 = st.seg_temp0 = None
                st.rec_samples = []
                self._persist()

    # --------------------------------------------------------------- output
    def offset_for(self, zone: str, fallback: float) -> float:
        """Learned setback offset for a room, or the fixed fallback."""
        if not self.enabled:
            return fallback
        st = self.rooms.get(zone)
        if (
            st is None
            or st.cycles < MIN_CYCLES
            or st.warm_ema is None
        ):
            return fallback
        depth = st.warm_ema * RECOVERY_TARGET_H
        return max(LEARNED_MIN_C, min(LEARNED_MAX_C, -depth))

    def as_dict(self) -> dict[str, Any]:
        rooms = {}
        for name, st in self.rooms.items():
            rooms[name] = {
                "cycles": st.cycles,
                "mature": st.cycles >= MIN_CYCLES,
                "learned_offset": (
                    round(self.offset_for(name, float("nan")), 2)
                    if st.cycles >= MIN_CYCLES else None
                ),
                "warm_rate": round(st.warm_ema, 2) if st.warm_ema else None,
                "cool_rate": round(st.cool_ema, 2) if st.cool_ema else None,
            }
        return {"enabled": self.enabled, "rooms": rooms}
