"""Estimated gas consumption from boiler telemetry — no meter needed.

OpenTherm has no standard gas-consumption ID, but every boiler that
reports burner state gives us enough to integrate burn over time:

  Modulating boilers   rate_kW = P_min + (P_max - P_min) x mod%/100
  ΔT hydronic          rate_kW = P_max × (Tflow−Tret) / ΔT_design / η
  On/off boilers       rate_kW = P_max x nomod_factor   (while flame on)

Priority while flame is ON:
  1. modulation % (nameplate input — best for gas burned)
  2. flow/return ΔT (physical heat-to-water, inverted through η)
  3. nameplate × nomod_factor (last resort)

P_max / P_min are the boiler's NAMEPLATE heat-INPUT range in kW.
The optional calibration factor matches a real gas meter after a day or two.

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

# Radiator systems are typically designed for ~20 K flow−return at full load.
# Q_delivered ≈ P_max × ΔT / DESIGN_DT  (heat to water, kW)
DESIGN_DT_K = 20.0
MIN_DT_K = 1.0          # below this, treat as no useful heat transfer
MAX_DT_K = 40.0         # sanity clamp (sensor glitch / DHW spike)
# Average seasonal efficiency when inverting delivered → gas input.
# Condensing boilers ~0.90–0.97; 0.90 keeps the gas estimate slightly high.
DEFAULT_EFFICIENCY = 0.90


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
        self.last_hydronic_kw: float | None = None
        self.last_dt_k: float | None = None
        self.mode: str = "waiting"   # waiting | modulating | ΔT estimate | on/off

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
    def hydronic_kw(
        self,
        flow_temp: float | None,
        return_temp: float | None,
        *,
        efficiency: float = DEFAULT_EFFICIENCY,
    ) -> tuple[float | None, float | None]:
        """Heat-to-water kW and ΔT from flow/return, or (None, None).

        Uses design mass-flow implied by nameplate at DESIGN_DT_K:
            Q_del = P_max × ΔT / DESIGN_DT
        Returns (delivered_kw, delta_t_k). Gas-input equivalent is
        delivered / efficiency (caller decides).
        """
        if flow_temp is None or return_temp is None:
            return None, None
        try:
            dtk = float(flow_temp) - float(return_temp)
        except (TypeError, ValueError):
            return None, None
        if dtk < MIN_DT_K:
            return 0.0, dtk
        dtk_c = min(MAX_DT_K, dtk)
        delivered = self.p_max_kw * (dtk_c / DESIGN_DT_K)
        return max(0.0, delivered), dtk

    def current_rate_kw(
        self,
        *,
        flame_on: bool,
        modulation: float | None,
        flow_temp: float | None = None,
        return_temp: float | None = None,
    ) -> tuple[float, str]:
        """Burner heat-input rate right now (kW) and the mode label."""
        hyd, dtk = self.hydronic_kw(flow_temp, return_temp)
        self.last_hydronic_kw = None if hyd is None else round(hyd, 3)
        self.last_dt_k = None if dtk is None else round(dtk, 2)

        if not flame_on:
            return 0.0, self.mode if self.mode != "waiting" else "off"

        usable_mod = (
            modulation if (modulation is not None and 0 < modulation <= 100) else None
        )
        if usable_mod is not None:
            self._saw_modulation = True
            span = self.p_max_kw - self.p_min_kw
            gas = self.p_min_kw + span * usable_mod / 100.0
            if hyd is not None and hyd > 0:
                return gas, "modulating+ΔT"
            return gas, "modulating"

        # No modulation: prefer physical ΔT over crude on/off duty.
        if hyd is not None and hyd > 0:
            eta = max(0.5, min(1.0, DEFAULT_EFFICIENCY))
            return hyd / eta, "ΔT estimate"

        return self.p_max_kw * self.nomod_factor, "on/off estimate"

    def feed(
        self,
        *,
        now: float | None = None,
        flame_on: bool | None = None,
        modulation: float | None = None,
        flow_temp: float | None = None,
        return_temp: float | None = None,
    ) -> float:
        """Integrate since the previous call; returns this step's kWh."""
        t = time.time() if now is None else float(now)
        dt = 0.0
        if self._last_t is not None:
            dt = min(max(t - self._last_t, 0.0), MAX_DT_S)
        self._last_t = t
        if dt <= 0.0:
            self.last_rate_kw = None
            return 0.0

        rate, mode = self.current_rate_kw(
            flame_on=bool(flame_on),
            modulation=modulation,
            flow_temp=flow_temp,
            return_temp=return_temp,
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
            "last_hydronic_kw": self.last_hydronic_kw,
            "last_dt_k": self.last_dt_k,
        }
        if price:
            out["today_cost"] = round(today * price, 2)
            out["price_per_kwh"] = price
        return out
