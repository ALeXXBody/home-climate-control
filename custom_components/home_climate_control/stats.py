"""Long-lived statistics for the Home Climate Control panel.

Buckets are one entry per local day, kept in the HA Store so they survive
HA restarts *and* integration updates (unlike RAM-only telemetry), and can
be wiped by the panel's Statistics → Reset button (which also zeroes the
gas meter so "since reset" stays coherent).

Aggregates per day:
    gas_kwh   — boiler gas use (mirrored from the gas meter day-buckets)
    cost      — gas price applied (when a price is configured)
    degmin    — Σ total_demand × interval (heat demand; correlates with
                outdoor temperature on the stats scatter)
    out_min/avg/max — outdoor temperature statistics
    burner_s / ch_s — seconds of flame / CH demand (tick-integrated)
    flow_sum/flow_n — average flow setpoint
"""

from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = "home_climate_control_stats"
STORAGE_VERSION = 1
KEEP_DAYS = 110          # ~14 months; storage stays a few KB
PERSIST_EVERY_S = 600    # flush cadence (also flushed on unload/reset)


class HccStats:
    """Daily statistics collector — fed by the control-tick loop."""

    def __init__(self, hass, *, gas_meter=None,
                 price_per_kwh: float | None = None) -> None:
        self.hass = hass
        self.gas_meter = gas_meter
        self.price_per_kwh = (
            float(price_per_kwh) if price_per_kwh else None
        )
        self.days: dict[str, dict[str, float]] = {}
        self._last_t = 0.0
        self._last_persist = 0.0
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY) if hass else None

    # ------------------------------------------------------------- storage
    async def async_load(self) -> None:
        if self._store is None:
            return
        try:
            data = await self._store.async_load() or {}
        except Exception:  # noqa: BLE001 - storage never blocks setup
            data = {}
        self.days = {
            str(k): dict(v) for k, v in (data.get("days") or {}).items()
        }
        if self.days:
            _LOGGER.info("Statistics restored: %d day buckets", len(self.days))

    async def async_save(self) -> None:
        if self._store is None:
            return
        try:
            await self._store.async_save({"version": 1, "days": self.days})
        except Exception:  # noqa: BLE001
            _LOGGER.debug("stats persist failed", exc_info=True)

    def schedule_save(self) -> None:
        if self.hass is None:
            return
        now = time.time()
        if now - self._last_persist < PERSIST_EVERY_S:
            return
        self._last_persist = now
        self.hass.async_create_task(self.async_save())

    def _prune(self) -> None:
        if len(self.days) > KEEP_DAYS:
            self.days = dict(sorted(self.days.items())[-KEEP_DAYS:])

    async def async_unload(self) -> None:
        await self.async_save()

    # ------------------------------------------------------------ sampling
    def observe(self, *, now: float | None = None, outdoor=None,
                total_demand: float = 0.0, burner_on: bool = False,
                ch_on: bool = False, flow_setpoint=None,
                latest_max_demand: float | None = None) -> None:
        """One control tick (≈ every CONTROL_LOOP_SECONDS). Cheap + sync."""
        import datetime as dtmod

        t = float(now) if now is not None else time.time()
        day = dtmod.datetime.fromtimestamp(t).strftime("%Y-%m-%d")
        d = self.days.get(day)
        if d is None:
            d = {
                "gas_kwh": 0.0, "cost": 0.0, "degmin": 0.0,
                "out_sum": 0.0, "out_min": None, "out_max": None,
                "out_n": 0.0, "burner_s": 0.0, "ch_s": 0.0,
                "flow_sum": 0.0, "flow_n": 0.0, "max_demand": 0.0,
            }
            self.days[day] = d
        try:
            ov = float(outdoor) if outdoor is not None else None
        except (TypeError, ValueError):
            ov = None
        if ov is not None:
            d["out_sum"] += ov
            d["out_n"] += 1
            d["out_min"] = ov if d["out_min"] is None else min(d["out_min"], ov)
            d["out_max"] = ov if d["out_max"] is None else max(d["out_max"], ov)
        tick = self._tick_s(t)
        d["degmin"] += float(total_demand or 0.0) * tick
        if latest_max_demand is not None:
            d["max_demand"] = max(d.get("max_demand", 0.0), float(latest_max_demand))
        if burner_on:
            d["burner_s"] += tick
        if ch_on:
            d["ch_s"] += tick
        if flow_setpoint is not None:
            try:
                d["flow_sum"] += float(flow_setpoint)
                d["flow_n"] += 1
            except (TypeError, ValueError):
                pass
        if self.gas_meter is not None:
            try:
                gas = float((self.gas_meter.days or {}).get(day, 0.0))
                d["gas_kwh"] = round(gas, 3)
                if self.price_per_kwh:
                    d["cost"] = round(gas * self.price_per_kwh, 4)
            except Exception:  # noqa: BLE001
                pass
        self._prune()
        self.schedule_save()

    def reset(self) -> None:
        """Clear every bucket (panel Reset) and zero the gas meter."""
        self.days = {}
        meter = self.gas_meter
        if meter is not None:
            meter.days = {}
            meter.total_kwh = 0.0
            meter._last_t = None
            meter.last_rate_kw = None
            # Persist the zeroed meter too — otherwise the old totals are
            # restored from the meter Store on the next HA restart and the
            # "since reset" gas figures come back while stats stay empty.
            try:
                meter._persist(force=True)
            except Exception:  # noqa: BLE001
                pass
        if self.hass is not None:
            self.hass.async_create_task(self.async_save())

    def _tick_s(self, now: float) -> float:
        if self._last_t <= 0.0:
            self._last_t = now
            return 0.0
        dt = min(max(now - self._last_t, 0.0), 120.0)
        self._last_t = now
        return dt

    # ------------------------------------------------------------- output
    def days_list(self, limit: int = 110) -> list[dict[str, Any]]:
        out = []
        for k in sorted(self.days)[-limit:]:
            d = self.days[k]
            out.append({
                "day": k,
                "gas_kwh": round(d.get("gas_kwh", 0.0), 2),
                "cost": (round(d.get("cost", 0.0), 2)
                         if self.price_per_kwh else None),
                "heat_degmin": round(d.get("degmin", 0.0), 1),
                "out_avg": (round(d["out_sum"] / d["out_n"], 1)
                            if d.get("out_n") else None),
                "out_min": (None if d.get("out_min") is None
                            else round(d["out_min"], 1)),
                "out_max": (None if d.get("out_max") is None
                            else round(d["out_max"], 1)),
                "burner_h": round(d.get("burner_s", 0.0) / 3600.0, 2),
                "ch_h": round(d.get("ch_s", 0.0) / 3600.0, 2),
                "flow_avg": (round(d["flow_sum"] / d["flow_n"], 1)
                             if d.get("flow_n") else None),
                "max_demand": round(d.get("max_demand", 0.0), 1),
            })
        return out

    def summary(self) -> dict[str, Any]:
        rows = self.days_list()

        def sum_key(key: str, days: int) -> float:
            return round(sum(r.get(key) or 0.0 for r in rows[-days:]), 2)

        return {
            "today": rows[-1] if rows else None,
            "gas_kwh_7d": sum_key("gas_kwh", 7),
            "gas_kwh_30d": sum_key("gas_kwh", 30),
            "cost_7d": (sum_key("cost", 7) if self.price_per_kwh else None),
            "cost_30d": (sum_key("cost", 30) if self.price_per_kwh else None),
            "heat_degmin_30d": sum_key("heat_degmin", 30),
            "burner_h_30d": sum_key("burner_h", 30),
            "price_per_kwh": self.price_per_kwh,
            "days": len(rows),
        }

    def _trend(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        """Least-squares slope: gas kWh per °C of outdoor temperature
        (the demand-weather correlation the panel plots)."""
        pairs = [(r["out_avg"], r["gas_kwh"]) for r in rows
                 if r.get("out_avg") is not None]
        if len(pairs) < 10:
            return {"slope": None, "intercept": None, "points": len(pairs)}
        n = len(pairs)
        mx = sum(p[0] for p in pairs) / n
        my = sum(p[1] for p in pairs) / n
        ssx = sum((p[0] - mx) ** 2 for p in pairs)
        ssxy = sum((p[0] - mx) * (p[1] - my) for p in pairs)
        slope = round(ssxy / ssx, 4) if ssx else None
        intercept = round(my - slope * mx, 2) if slope is not None else None
        return {"slope": slope, "intercept": intercept, "points": n}

    def as_dict(self) -> dict[str, Any]:
        rows = self.days_list()
        return {
            "summary": self.summary(),
            "rows": rows[-60:],
            "trend": self._trend(rows),
        }
