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
from .calibrate import RoomCalibrator
from .const import CONTROL_LOOP_SECONDS, DEFAULT_MAX_FLOW_TEMP
from .health import FLOW_NEAR_MAX_K, RoomHealthMonitor
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
        self.setbacks = None
        self.gas = None
        self.deadtime = None
        self.insulation = None
        self.datalogger = None
        from .cycleguard import CycleGuard

        self.cycleguard = CycleGuard()
        self.calibration = RoomCalibrator()
        self.health = RoomHealthMonitor()

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

    # ------------------------------------------------------------ calibration
    def _find_zone(self, zone_name: str):
        for z in self.zones:
            if getattr(z, "name", None) == zone_name:
                return z
        return None

    # ---------------------------------------------------------- zone admin
    def rename_zone_learning(self, old: str, new: str) -> None:
        """Carry every learned coefficient over when a room is renamed.

        Setback offsets, dead-time and insulation scores take days or weeks
        to mature — a rename must never throw that history away.
        """
        for store in (self.setbacks, self.deadtime, self.insulation):
            if store is None:
                continue
            rooms = getattr(store, "rooms", None)
            if rooms and old in rooms and new not in rooms:
                rooms[new] = rooms.pop(old)
            persist = getattr(store, "_persist", None)
            if callable(persist):
                persist()
        if self.deadtime is not None:
            est = self.deadtime.estimates
            if old in est and new not in est:
                est[new] = est.pop(old)
            self.deadtime._persist()
        if old in self.health.rooms and new not in self.health.rooms:
            self.health.rooms[new] = self.health.rooms.pop(old)
        if self.calibration.active_zone == old:
            # A session cannot survive the entity reload anyway.
            self.calibration.cancel()

    async def async_start_calibration(self, zone_name: str) -> dict:
        """Bootstrap a room's heat-rate: boost its target, time the climb.

        The boosted setpoint guarantees the room actually calls for heat;
        the calibrator measures °C/h from live sensor updates and
        finish_calibration() restores everything afterwards.
        """
        zone = self._find_zone(zone_name)
        if zone is None:
            raise ValueError(f"unknown zone '{zone_name}'")
        if self.calibration.active():
            raise RuntimeError(
                f"calibration already running for '{self.calibration.active_zone}'"
            )
        cur = (
            getattr(zone, "current_temperature", None)
            or getattr(zone, "_current_temp", None)
        )
        if cur is None:
            raise ValueError(f"no temperature reading for '{zone_name}' yet")

        entity_id = getattr(zone, "entity_id", None)
        if not entity_id:
            raise ValueError(f"zone '{zone_name}' has no climate entity yet")

        original = getattr(zone, "_target_temp", None)
        boosted = round(max(cur + 2.0, original or 0.0) + 0.0, 1)
        self._calib_restore = {
            "entity_id": entity_id,
            "temperature": original,
            "prev_hvac": str(getattr(zone, "hvac_mode", "off")),
        }
        self.calibration.start(zone_name, temp=cur)

        await self.hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": entity_id, "temperature": boosted},
            blocking=True,
        )
        if str(getattr(zone, "hvac_mode", "heat")) != "heat":
            await self.hass.services.async_call(
                "climate",
                "set_hvac_mode",
                {"entity_id": entity_id, "hvac_mode": "heat"},
                blocking=True,
            )
        _LOGGER.info(
            "Calibration: '%s' target %.1f → %.1f °C (from %.1f °C room temp)",
            zone_name,
            original if original is not None else -99.0,
            boosted,
            cur,
        )
        return {"ok": True, "zone": zone_name, "boosted_to": boosted}

    async def async_cancel_calibration(self) -> dict:
        res = self.calibration.cancel()
        await self._restore_after_calibration()
        return {"ok": True, **res}

    async def finish_calibration(self, result: dict) -> None:
        """Called when the calibrator closes a session (done/partial/failed)."""
        await self._restore_after_calibration()
        rate = result.get("rate_cph")
        if result.get("status") in ("done", "partial") and rate and self.setbacks:
            self.setbacks.inject_warm_rate(result["zone"], rate)

    async def _restore_after_calibration(self) -> None:
        restore = getattr(self, "_calib_restore", None)
        if not restore:
            return
        self._calib_restore = None
        try:
            if restore.get("temperature") is not None:
                await self.hass.services.async_call(
                    "climate",
                    "set_temperature",
                    {
                        "entity_id": restore["entity_id"],
                        "temperature": restore["temperature"],
                    },
                    blocking=True,
                )
            prev_hvac = restore.get("prev_hvac")
            if prev_hvac:
                await self.hass.services.async_call(
                    "climate",
                    "set_hvac_mode",
                    {
                        "entity_id": restore["entity_id"],
                        "hvac_mode": prev_hvac,
                    },
                    blocking=True,
                )
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Restoring setpoint after calibration failed")

    def _calibration_tick(self, _now: float) -> None:
        """Expire stale sessions; runs inside the control tick."""
        import time as _time

        res = self.calibration.maybe_expire(_time.time())
        if res is not None and self.hass is not None:
            self.hass.async_create_task(self.finish_calibration(res))

    async def _async_control_tick(self, _now=None) -> None:
        try:
            await self.async_control_step()
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Control tick failed")

    async def async_control_step(self) -> None:
        import time as _time

        now = _time.monotonic()

        # Calibration sessions can time out; check on every tick.
        self._calibration_tick(now)

        # Gas accounting: integrate burner kW x dt from live telemetry.
        if self.gas is not None:
            try:
                self.gas.feed(
                    now=_time.time(),
                    flame_on=bool(getattr(self.backend, "flame_on", False) or False),
                    modulation=getattr(self.backend, "modulation_level", None),
                )
            except Exception:  # noqa: BLE001
                _LOGGER.debug("gas feed failed", exc_info=True)
        outdoor = self.outdoor_temp()
        demanding = [z for z in self.zones if z.wants_heat() and not z.paused()]

        # CycleGuard owns the actual CH on/off decision: it enforces a
        # minimum burn length and an adaptive rest window so a flickering
        # thermostat signal cannot turn the boiler into a stop-start mess.
        desired_ch = bool(demanding)
        ch_state, _reason = self.cycleguard.decide(desired_ch, self._ch_on, now)
        if ch_state != self._ch_on:
            await self.backend.async_set_ch_enabled(ch_state)
            self.cycleguard.record(ch_state, now)
            self._ch_on = ch_state
            if ch_state:
                _LOGGER.info("CH on (%s)", _reason)
                # Dead-time stopwatches: rooms demanding at this instant are
                # timed until their temperature starts to move.
                if self.deadtime is not None:
                    import time as _time

                    temps = {}
                    for z in demanding:
                        t = (
                            getattr(z, "current_temperature", None)
                            or getattr(z, "_current_temp", None)
                        )
                        if t is not None:
                            temps[z.name] = t
                    self.deadtime.arm(
                        [z.name for z in demanding],
                        ts=_time.time(),
                        temps=temps,
                    )
            else:
                _LOGGER.info("CH off (%s)", _reason)
                if self.deadtime is not None:
                    self.deadtime.disarm_all()

        if not ch_state and not self._ch_on:
            # Fully at rest: no demand honoured this tick.
            if not demanding:
                self.flow_setpoint = None
                self.total_demand = 0.0
                self.active_zone_names = []
                self.estimated_gas_percent = 0.0
        elif demanding:
            # Burner allowed to fire and zones want heat: compute the flow
            # target. (If demand vanished mid-min-on-floor we deliberately
            # keep the previous setpoint: the burner finishes its short
            # minimum burn at low fire while TRVs throttle.)
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

        # Health watch: a room that demands heat with a large deficit while
        # flow runs saturated is struggling (undersized/blocked radiator or
        # stuck TRV). Feed every room each tick so flags can also clear.
        flow_now = self.flow_setpoint
        sat = bool(
            self._ch_on
            and flow_now is not None
            and flow_now >= self.max_flow - FLOW_NEAR_MAX_K
        )
        for z in self.zones:
            dem = bool(z.wants_heat() and not z.paused())
            cur = (
                getattr(z, "current_temperature", None)
                or getattr(z, "_current_temp", None)
            )
            deficit = (z.effective_setpoint() - cur) if cur is not None else None
            try:
                self.health.feed(
                    z.name,
                    now,
                    demanding=dem,
                    deficit_c=deficit,
                    flow_at_max=sat,
                    tick_s=CONTROL_LOOP_SECONDS,
                )
            except Exception:  # noqa: BLE001
                _LOGGER.debug("health feed failed", exc_info=True)

        # Training-data log: one compact snapshot per control tick (60 s).
        if self.datalogger is not None:
            try:
                self.datalogger.feed(self._training_row())
            except Exception:  # noqa: BLE001
                _LOGGER.debug("training feed failed", exc_info=True)

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

    def _training_row(self) -> dict:
        """Flat, ML-friendly snapshot of the whole system for this tick."""
        from datetime import datetime, timezone

        zones_out = []
        for z in self.zones:
            cur = (
                getattr(z, "current_temperature", None)
                or getattr(z, "_current_temp", None)
            )
            zr = {
                "name": getattr(z, "name", None),
                "floor": getattr(z, "floor", 0),
                "heat_control": getattr(z, "heater_control", "smart"),
                "temp": cur,
                "target": getattr(z, "_target_temp", None),
                "effective_setpoint": z.effective_setpoint(),
                "preset": getattr(z, "_preset", None),
                "demand": z.demand_level(),
                "wants_heat": bool(z.wants_heat() and not z.paused()),
                "hvac_action": str(getattr(z, "hvac_action", "")),
                "window_open": bool(z.paused()),
                "health_flag": self.health.flag_for(getattr(z, "name", "")),
            }
            if self.setbacks is not None:
                st = self.setbacks.rooms.get(zr["name"])
                if st is not None:
                    zr["warm_rate"] = st.warm_ema
                    zr["cool_rate"] = st.cool_ema
            if self.deadtime is not None:
                zr["dead_time_s"] = self.deadtime.seconds_for(zr["name"])
            lead = getattr(z, "lead_time_s", None)
            if callable(lead):
                try:
                    ls = lead(to_comfort=zr.get("preset") in ("away", "eco"))
                except Exception:  # noqa: BLE001
                    ls = None
                if ls is not None:
                    zr["lead_time_s"] = round(ls, 0)
            if getattr(z, "_preheat_active", False):
                zr["preheat"] = True
            if self.insulation is not None:
                sc = self.insulation.score_for(zr["name"])
                if sc is not None:
                    zr["insulation_k"] = round(sc[1], 5)
            zones_out.append(zr)

        backend = self.backend
        return {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "outdoor": self.outdoor_temp(),
            "ch_on": self._ch_on,
            "flow_setpoint": self.flow_setpoint,
            "curve_coeff": self.curve_coeff,
            "boiler": {
                "flame": bool(getattr(backend, "flame_on", False)),
                "modulation": getattr(backend, "modulation_level", None),
                "return_t": getattr(backend, "return_temp", None),
                "flow_t": getattr(backend, "flow_temp", None),
            },
            "zones": zones_out,
        }

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
        if self.setbacks is not None:
            data["setbacks"] = self.setbacks.as_dict()
        if self.deadtime is not None:
            data["deadtime"] = self.deadtime.as_dict()
        if self.insulation is not None:
            data["insulation"] = self.insulation.as_dict()
        if self.datalogger is not None:
            data["datalogger"] = self.datalogger.stats()
        data["calibration"] = self.calibration.as_dict()
        data["health"] = self.health.as_dict()
        if self.gas is not None:
            data["gas"] = self.gas.as_dict()
        data["cycle_guard"] = self.cycleguard.as_dict()
        data.update(self.backend.diagnostics())
        data["boiler_connected"] = getattr(self.backend, "connected", True)
        return data
