"""Estimated gas consumption from boiler telemetry — no meter needed.

OpenTherm has no standard gas-consumption ID, but every boiler that
reports burner state gives us enough to integrate burn over time:

  Modulating boilers   rate_kW = P_min + (P_max - P_min) x mod%/100
  On/off boilers       rate_kW = P_max x nomod_factor   (while flame on)

where P_max / P_min are the boiler's NAMEPLATE heat-INPUT range in kW
(what the data plate calls "central heating input", not output). The
linear interpolation between min and max firing is a good model for
condensing boilers across all brands; the optional calibration factor
lets anyone match their actual gas meter exactly after a day or two.

Hot-water (DHW) burns count too — it is house gas either way.
Accumulation only runs while the flame is reported ON, so pump-only
circulation never adds kWh.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = "home_climate_control_gasmeter"
STORAGE_VERSION = 1

KEEP_DAYS = 14          # per-day buckets retained for panel/history
MAX_DT_S = 300.0        # ignore integration gaps longer than this
PERSIST_EVERY_S = 300   # throttle Store writes


class GasMeter:
    """Integrates kW x time into kWh/day buckets from backend telemetry."""

    def __init__(
        self,
        hass,
        *,
        rated_power_kw: float = 24.0,
        min_power_kw: float = 0.0,
        nomod_factor: float = 0.6,
        calibration: float = 1.0,
        price_per_kwh: float | None = None,
    ) -> None:
        self.hass = hass
        self.p_max_kw = max(0.5, float(rated_power_kw))
        self.p_min_kw = min(max(0.0, float(min_power_kw)), self.p_max_kw)
        self.nomod_factor = min(max(0.05, float(nomod_factor)), 1.0)
        self.calibration = max(0.01, float(calibration))
        self.price_per_kwh = (
            float(price_per_kwh) if price_per_kwh else None
        )

        self.total_kwh = 0.0
        self.days: dict[str, float] = {}
        self._last_t: float | None = None
        self._last_persist = 0.0
        self._saw_modulation = False
        self.last_rate_kw: float | None = None
        self.mode: str = "waiting"   # waiting | modulating | on/off estimate

        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY) if hass else None

    # ------------------------------------------------------------------ I/O
    async def async_load(self) -> None:
        if self._store is None:
            return
        try:
            data = await self._store.async_load() or {}
        except Exception:  # noqa: BLE001
            data = {}
        self.total_kwh = float(data.get("total_kwh", 0.0))
        self.days = {
            str(k): float(v)
            for k, v in (data.get("days") or {}).items()
        }
        if self.total_kwh or self.days:
            _LOGGER.info(
                "GasMeter restored %.1f kWh total (%d days)",
                self.total_kwh,
                len(self.days),
            )

    def _persist(self, force: bool = False) -> None:
        if self._store is None:
            return
        now = time.time()
        if not force and now - self._last_persist < PERSIST_EVERY_S:
            return
        self._last_persist = now

        payload = {
            "total_kwh": round(self.total_kwh, 4),
            "days": dict(
                sorted(self.days.items())[-KEEP_DAYS:]
            ),
        }

        async def _save() -> None:
            try:
                await self._store.async_save(payload)
            except Exception:  # noqa: BLE001
                _LOGGER.debug("gasmeter persist failed", exc_info=True)

        if self.hass is not None and hasattr(self.hass, "async_create_task"):
            self.hass.async_create_task(_save())
        else:
            import asyncio

            try:
                asyncio.get_running_loop()
                asyncio.ensure_future(_save())
            except RuntimeError:
                asyncio.run(_save())

    # -------------------------------------------------------------- physics
    def current_rate_kw(self, *, flame_on: bool, modulation: float | None) -> tuple[float, str]:
        """Burner heat-input rate right now (kW) and the mode label."""
        if not flame_on:
            return 0.0, self.mode if self.mode != "waiting" else "off"
        usable_mod = modulation if (modulation is not None and 0 < modulation <= 100) else None
        if usable_mod is not None:
            self._saw_modulation = True
            span = self.p_max_kw - self.p_min_kw
            return self.p_min_kw + span * usable_mod / 100.0, "modulating"
        # No trustworthy modulation signal: nameplate duty estimate.
        return self.p_max_kw * self.nomod_factor, "on/off estimate"

    def feed(self, *, now: float | None = None,
             flame_on: bool | None = None,
             modulation: float | None = None) -> float:
        """Integrate since the previous call; returns this step's kWh.

        flame_on/modulation default to reading self.backend if attached;
        tests pass them explicitly with an injected clock.
        """
        t = time.time() if now is None else float(now)
        dt = 0.0
        if self._last_t is not None:
            dt = min(max(t - self._last_t, 0.0), MAX_DT_S)
        self._last_t = t
        if dt <= 0.0:
            self.last_rate_kw = None
            return 0.0

        rate, mode = self.current_rate_kw(
            flame_on=bool(flame_on), modulation=modulation
        )
        self.mode = mode
        self.last_rate_kw = round(rate, 3)

        kwh = rate * dt / 3600.0 * self.calibration
        if kwh > 0:
            self.total_kwh += kwh
            day = datetime.fromtimestamp(t).strftime("%Y-%m-%d")
            self.days[day] = self.days.get(day, 0.0) + kwh
            self._persist()
        return kwh

    # --------------------------------------------------------------- output
    def today_kwh(self) -> float:
        day = datetime.now().strftime("%Y-%m-%d")
        return self.days.get(day, 0.0)

    def as_dict(self) -> dict[str, Any]:
        week = [
            {"day": d, "kwh": round(v, 2)}
            for d, v in sorted(self.days.items())[-7:]
        ]
        price = self.price_per_kwh
        today = round(self.today_kwh(), 2)
        out = {
            "mode": self.mode,
            "rated_power_kw": self.p_max_kw,
            "min_power_kw": self.p_min_kw,
            "calibration": self.calibration,
            "today_kwh": today,
            "total_kwh": round(self.total_kwh, 2),
            "week": week,
            "last_rate_kw": self.last_rate_kw,
        }
        if price:
            out["today_cost"] = round(today * price, 2)
            out["price_per_kwh"] = price
        return out
