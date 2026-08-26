"""Dead-time estimation — how long until a room *responds* to the boiler.

Turn the boiler on and nothing visible happens for a while: water must
travel, the radiator must warm, the air around the sensor must follow.
That delay is dead time, and every "start heating so it's warm by 7:00"
decision depends on knowing it per room:

    start_time = target_time - dead_time - recovery_time

This estimator measures it passively from normal operation:

1. The controller announces a heat start ("CH just came on") together with
   the rooms that were demanding heat — their stopwatches are armed.
2. Each room's temperature samples are watched; the stopwatch stops at the
   first sustained rise above that room's level when the event began.
3. The measured delay is sanity-clamped and EMA-smoothed into a per-room
   estimate, persisted across restarts like the setback learner.

Rooms that stopped demanding before responding are disarmed quietly;
measurements taken while a window pause is active would describe open-air
physics, not the heating system, and are discarded.

Pure logic module: no Home Assistant imports, fully unit-testable.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = "home_climate_control_deadtime"
STORAGE_VERSION = 1

RISE_EPS_C = 0.0           # (reserved) minimum per-sample rise
CONSEC_RISE_N = 2          # consecutive rising samples required (jitter filter)
DT_MIN_S = 45              # faster than this is noise
DT_MAX_S = 45 * 60         # slower than this looks like a broken system
EMA_ALPHA = 0.30           # smoothing for per-room estimates


class _RoomState:
    __slots__ = ("armed", "t0", "baseline", "prev_temp", "rises")

    def __init__(self) -> None:
        self.armed = False
        self.t0: float | None = None
        self.baseline: float | None = None
        self.prev_temp: float | None = None
        self.rises = 0


class DeadTimeEstimator:
    """Tracks per-room response delays to global heat starts."""

    def __init__(self, hass, *, enabled: bool = True) -> None:
        self.hass = hass
        self.enabled = enabled
        self.rooms: dict[str, _RoomState] = {}
        self.estimates: dict[str, float] = {}  # zone -> seconds (raw EMA)
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
            v = r.get("seconds")
            if isinstance(v, (int, float)):
                self.estimates[name] = float(v)
        if data:
            _LOGGER.info("Dead-time estimates restored for %d room(s)", len(data))

    def _persist(self) -> None:
        if self._store is None:
            return
        payload = {name: {"seconds": sec} for name, sec in self.estimates.items()}

        async def _save() -> None:
            try:
                await self._store.async_save(payload)
            except Exception:  # noqa: BLE001
                _LOGGER.debug("deadtime persist failed", exc_info=True)

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

    # --------------------------------------------------------------- control
    def arm(self, zones: list[str], ts: float | None = None, temps: dict[str, float] | None = None) -> None:
        """A heat start happened: arm the given demanding rooms."""
        ts = ts if ts is not None else time.time()
        temps = temps or {}
        for z in zones:
            st = self._room(z)
            st.armed = True
            st.t0 = ts
            st.baseline = temps.get(z)
            st.prev_temp = st.baseline
            st.rises = 0

    def disarm_all(self, ts: float | None = None) -> None:
        """Heat ended before some rooms responded; drop those stopwatches."""
        for st in self.rooms.values():
            st.armed = False
            st.t0 = None

    def invalidate(self, zone: str) -> None:
        """Window opened / physics no longer ours: drop this room's run."""
        st = self.rooms.get(zone)
        if st:
            st.armed = False
            st.t0 = None

    def observe(self, zone: str, ts: float, temp: float) -> float | None:
        """Feed one sample; returns the freshly-updated estimate or None."""
        st = self.rooms.get(zone)
        if not self.enabled or st is None or not st.armed or temp is None:
            return None
        if st.baseline is None:
            # First sample after arming anchors the comparison level.
            st.baseline = temp
            st.prev_temp = temp
            return None

        # A "response" is a short run of consecutive increasing samples —
        # measured from the previous sample, not from the pre-event level,
        # so a deep initial fall doesn't hide the moment the room turns.
        if temp > st.prev_temp:
            st.rises += 1
        else:
            st.rises = 0
        st.prev_temp = temp

        if st.rises >= CONSEC_RISE_N:
            dt = ts - st.t0 if st.t0 is not None else 0.0
            st.armed = False
            st.t0 = None
            if DT_MIN_S <= dt <= DT_MAX_S:
                old = self.estimates.get(zone)
                est = dt if old is None else old + EMA_ALPHA * (dt - old)
                self.estimates[zone] = est
                self._persist()
                _LOGGER.info(
                    "'%s' responded %.1f min after heat start (estimate %.1f min)",
                    zone,
                    dt / 60.0,
                    est / 60.0,
                )
                return est
            _LOGGER.debug("'%s' dead-time %ds out of range — ignored", zone, int(dt))
        return None

    # ---------------------------------------------------------------- output
    def seconds_for(self, zone: str, fallback: float | None = None) -> float | None:
        return self.estimates.get(zone, fallback)

    def lead_for(
        self,
        zone: str,
        *,
        warm_cph: float | None,
        deficit_c: float,
    ) -> float | None:
        """Full optimal-start lead (dead-time + recovery) for one room."""
        from .preheat import lead_seconds

        if deficit_c is None:
            return None
        return lead_seconds(
            dead_s=self.seconds_for(zone),
            warm_cph=warm_cph,
            deficit_c=deficit_c,
        )

    def _room(self, zone: str) -> _RoomState:
        return self.rooms.setdefault(zone, _RoomState())

    def as_dict(self) -> dict[str, Any]:
        rooms = {}
        for name in sorted(set(self.rooms) | set(self.estimates)):
            st = self.rooms.get(name)
            rooms[name] = {
                "minutes": (
                    round(self.estimates[name] / 60.0, 1)
                    if name in self.estimates else None
                ),
                "seconds": (
                    round(self.estimates[name], 0)
                    if name in self.estimates else None
                ),
                "measuring": bool(st and st.armed),
            }
        return {"enabled": self.enabled, "rooms": rooms}
