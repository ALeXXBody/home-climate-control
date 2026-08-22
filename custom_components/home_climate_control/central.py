"""CentralController: demand aggregation + gas-optimal boiler command.

Control loop (every CONTROL_LOOP_SECONDS):
1. Gather zone demands (each zone reports error and requested flow temp).
2. Boiler flow setpoint = max(requested flow) across demanding zones,
   raised by the worst-zone PID contribution.
3. No demand anywhere -> CH off.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval

from .boiler.base import BoilerBackend
from .const import CONTROL_LOOP_SECONDS
from .heating_curve import clamp, flow_for_outdoor

_LOGGER = logging.getLogger(__name__)


class CentralController:
    """Coordinates zones and drives the boiler backend."""

    def __init__(
        self,
        hass: HomeAssistant,
        backend: BoilerBackend,
        *,
        curve_coeff: float,
        design_outdoor: float,
        min_flow: float,
        max_flow: float,
    ) -> None:
        self.hass = hass
        self.backend = backend
        self.curve_coeff = curve_coeff
        self.design_outdoor = design_outdoor
        self.min_flow = min_flow
        self.max_flow = max_flow

        self.zones: list = []

        self.flow_setpoint: float | None = None
        self.total_demand: float = 0.0
        self.active_zone_names: list[str] = []
        self.estimated_gas_percent: float | None = None

        self._unsub_loop = None
        self._ch_on: bool = False

    async def async_start(self) -> None:
        await self.backend.async_start()
        self._unsub_loop = async_track_time_interval(
            self.hass, self._async_control_tick, timedelta(seconds=CONTROL_LOOP_SECONDS)
        )
        # Immediate first tick so the boiler reacts without waiting a full minute.
        await self.async_control_step()
        _LOGGER.info("Central controller started (%d zones)", len(self.zones))

    async def async_stop(self) -> None:
        if self._unsub_loop:
            self._unsub_loop()
            self._unsub_loop = None
        if self._ch_on:
            await self.backend.async_set_ch_enabled(False)
            self._ch_on = False
        await self.backend.async_stop()

    def register_zone(self, zone) -> None:
        if zone not in self.zones:
            self.zones.append(zone)

    def outdoor_temp(self) -> float | None:
        """Prefer boiler outdoor sensor from OTGW; optional HA sensor later."""
        return self.backend.outdoor_temp

    async def _async_control_tick(self, _now=None) -> None:
        try:
            await self.async_control_step()
        except Exception:  # noqa: BLE001 — keep the loop alive
            _LOGGER.exception("Control tick failed")

    async def async_control_step(self) -> None:
        outdoor = self.outdoor_temp()

        demanding = [z for z in self.zones if z.wants_heat() and not z.paused()]

        if not demanding:
            if self._ch_on:
                _LOGGER.info("No zone demand → CH off")
                await self.backend.async_set_ch_enabled(False)
                self._ch_on = False
            self.flow_setpoint = None
            self.total_demand = 0.0
            self.active_zone_names = []
            self.estimated_gas_percent = 0.0
            return

        max_setpoint = max(z.effective_setpoint() for z in demanding)
        base_flow = flow_for_outdoor(
            max_setpoint,
            outdoor if outdoor is not None else self.design_outdoor,
            self.curve_coeff,
            self.min_flow,
            self.max_flow,
            self.design_outdoor,
        )
        worst_pid_extra = max(z.pid_flow_contribution() for z in demanding)
        target_flow = clamp(base_flow + worst_pid_extra, self.min_flow, self.max_flow)

        if not self._ch_on:
            await self.backend.async_set_ch_enabled(True)
            self._ch_on = True
        await self.backend.async_set_flow_setpoint(target_flow)

        self.flow_setpoint = target_flow
        self.active_zone_names = [z.name for z in demanding]
        self.total_demand = sum(z.demand_level() for z in demanding)
        self.estimated_gas_percent = min(100.0, self.total_demand * 100.0)

        _LOGGER.debug(
            "tick: outdoor=%s flow=%.1f (base %.1f + pid %.1f) zones=%s",
            f"{outdoor:.1f}" if outdoor is not None else "?",
            target_flow,
            base_flow,
            worst_pid_extra,
            self.active_zone_names,
        )

    def diagnostics(self) -> dict:
        data = {
            "flow_setpoint": self.flow_setpoint,
            "total_demand": round(self.total_demand, 2),
            "active_zones": self.active_zone_names,
            "curve_coeff": self.curve_coeff,
            "design_outdoor": self.design_outdoor,
            "min_flow": self.min_flow,
            "max_flow": self.max_flow,
        }
        data.update(self.backend.diagnostics())
        return data
