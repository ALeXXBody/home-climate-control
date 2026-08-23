"""CentralController: demand aggregation + gas-optimal boiler command.

Control loop (every CONTROL_LOOP_SECONDS):
1. Gather zone demands (each zone reports error and requested flow temp).
2. Boiler flow setpoint = max(requested flow) across demanding zones,
   raised by the worst-zone PID contribution.
3. No demand anywhere -> CH off.
4. Demo backend: advance simulated boiler + room temperatures.
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
        autotune=None,
    ) -> None:
        self.hass = hass
        self.backend = backend
        self.curve_coeff = curve_coeff
        self.design_outdoor = design_outdoor
        self.min_flow = min_flow
        self.max_flow = max_flow
        self.autotune = autotune

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
            ensure = getattr(self.backend, "ensure_room", None)
            if callable(ensure):
                name = getattr(zone, "name", None) or "Zone"
                ensure(name, getattr(zone, "current_temperature", None) or 18.0)

    def outdoor_temp(self) -> float | None:
        return self.backend.outdoor_temp

    async def _async_control_tick(self, _now=None) -> None:
        try:
            await self.async_control_step()
        except Exception:  # noqa: BLE001
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
        else:
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

            # Auto-tune: feed aggregate comfort error, maybe learn a better
            # curve coefficient (gas mission: no chronic cold, no overshoot).
            if self.autotune is not None:
                errs = []
                for z in demanding:
                    cur = getattr(z, "current_temperature", None)
                    if cur is None:
                        cur = getattr(z, "_current_temp", None)
                    if cur is not None:
                        errs.append(z.effective_setpoint() - cur)
                if errs:
                    self.autotune.observe(sum(errs) / len(errs), True)
                    learned = self.autotune.step()
                    if learned is not None and learned != self.curve_coeff:
                        self.curve_coeff = learned
                else:
                    self.autotune.observe(None, False)

            _LOGGER.debug(
                "tick: outdoor=%s flow=%.1f (base %.1f + pid %.1f) zones=%s",
                f"{outdoor:.1f}" if outdoor is not None else "?",
                target_flow,
                base_flow,
                worst_pid_extra,
                self.active_zone_names,
            )

        # Demo physics + push simulated room temps into zones.
        simulate = getattr(self.backend, "simulate_step", None)
        if callable(simulate):
            simulate(self.zones)
            get_room = getattr(self.backend, "get_room_temp", None)
            if callable(get_room):
                for zone in self.zones:
                    name = getattr(zone, "name", None)
                    if not name:
                        continue
                    temp = get_room(name)
                    if temp is not None and hasattr(zone, "on_sensor_update"):
                        zone.on_sensor_update(temp, None)

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
        if self.autotune is not None:
            data["autotune"] = self.autotune.as_dict()
        data.update(self.backend.diagnostics())
        return data
