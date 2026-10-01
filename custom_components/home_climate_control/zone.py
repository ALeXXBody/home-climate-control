"""RoomClimateEntity: one heated room.

Architecture:
  HCS device  →  boiler gateway only (not part of any room)
  Room        →  one TRV climate entity + optional external temp sensor
                 If no external sensor is set, the TRV's own temperature is used.

HCC owns the room setpoint and drives boiler demand. The TRV is the actuator
in the room (and temperature source when no wall sensor is present).
"""

from __future__ import annotations

import logging
import math
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, PRECISION_HALVES, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.storage import Store

from .const import (
    CONF_ZONE_CO2_SENSOR,
    CONF_ZONE_HUMIDITY_SENSOR,
    CONF_ZONE_LUX_SENSOR,
    CONF_ZONE_RADIATOR_KW,
    CONF_ZONE_TRV_POSITION,
    DEFAULT_MAX_ROOM_TEMP,
    DEFAULT_MIN_ROOM_TEMP,
    DEFAULT_TARGET_STEP,
    DEFAULT_ZONE_SETPOINT,
    DEFAULT_PRESET_TEMPS,
    HEAT_CONTROL_VALVE,
    PID_INTEGRAL_CLAMP,
    PID_KI,
    PID_KP,
    VALVE_HYST_PCT,
    VALVE_MIN_PCT,
    VALVE_OPEN_DEMAND,
    VALVE_PIN_INTERVAL_S,
    VALVE_WRITE_INTERVAL_S,
    ZONE_PRESETS,
)
from .balancing import BalanceMonitor
from .co2 import Co2Guard
from .pid import PID
from .solar import SolarGain
from .window_detect import SlopeWindowDetector

_LOGGER = logging.getLogger(__name__)

def _as_list(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


class ZoneClimateEntity(ClimateEntity, RestoreEntity):
    """One heated room. Reports demand to the CentralController."""

    _attr_should_poll = False
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_preset_modes = ZONE_PRESETS

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator,
        entry: ConfigEntry,
        zone_cfg: dict[str, Any],
    ) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self._zone_cfg = zone_cfg

        name = zone_cfg["name"]
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_room_{name}"
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_precision = PRECISION_HALVES
        self._attr_min_temp = DEFAULT_MIN_ROOM_TEMP
        self._attr_max_temp = DEFAULT_MAX_ROOM_TEMP
        self._attr_target_temperature_step = DEFAULT_TARGET_STEP
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
        )

        # Room = TRV (+ optional external wall sensor). Legacy multi-TRV
        # configs are accepted (first TRV is primary).
        trvs = _as_list(zone_cfg.get("trv_climates") or zone_cfg.get("trv"))
        self._trv_climates: list[str] = trvs
        self._trv_entity: str | None = trvs[0] if trvs else None
        self._temp_sensor = zone_cfg.get("temp_sensor") or None
        self._window_sensors: list[str] = _as_list(zone_cfg.get("window_sensors"))
        # House-model fields: which floor the room sits on and how its heat
        # is controlled (smart = addressable TRV, manual = hand-turned valve
        # HCC can only observe).
        try:
            self.floor: int = max(0, int(zone_cfg.get("floor", 0) or 0))
        except (TypeError, ValueError):
            self.floor = 0
        control = str(zone_cfg.get("heat_control", "smart") or "smart").lower()
        self.heater_control: str = (
            control if control in ("smart", "valve", "manual") else "smart"
        )
        # Valve-direct drive state (rate-limit + pin bookkeeping).
        self._valve_last_write: float = 0.0
        self._valve_pin_at: float = 0.0
        self._valve_last_exercise: float = 0.0
        self._valve_exercising = False
        # Rooms without physical sensors get slope-based detection instead:
        # an abnormally fast temperature drop pauses heat just like a
        # tripped door sensor would.
        self._slope_detector = (
            None if self._window_sensors else SlopeWindowDetector()
        )

        start = zone_cfg.get("demo_start_temp")
        try:
            self._current_temp: float | None = (
                float(start) if start is not None else None
            )
        except (TypeError, ValueError):
            self._current_temp = None
        try:
            self._target_temp: float = float(
                zone_cfg.get("setpoint", DEFAULT_ZONE_SETPOINT)
            )
        except (TypeError, ValueError):
            self._target_temp = float(DEFAULT_ZONE_SETPOINT)
        self._preset: str = "none"
        # "schedule" = last change came from timetable; "user" = sticky
        # until the schedule entity itself advances to a new window.
        self._preset_source: str = "schedule"
        self._hvac_mode: HVACMode = (
            HVACMode.HEAT if zone_cfg.get("demo_start_temp") is not None else HVACMode.OFF
        )
        self._window_open: bool = False
        self._temp_from_trv: bool = False
        # Reactive optimal-start: True while catch-up heat is running during
        # an away/eco setback so the room is warm when the recovery window
        # would otherwise already be blown.
        self._preheat_active: bool = False

        # ── Tier 3/4 per-room extras ────────────────────────────────────
        self._lux_sensor = zone_cfg.get(CONF_ZONE_LUX_SENSOR) or None
        self._co2_sensor = zone_cfg.get(CONF_ZONE_CO2_SENSOR) or None
        self._humidity_sensor = zone_cfg.get(CONF_ZONE_HUMIDITY_SENSOR) or None
        self._humidity_pct: float | None = None
        self._humidity_from_trv: bool = False
        self._trv_position_entity = (
            zone_cfg.get(CONF_ZONE_TRV_POSITION) or None
        )
        try:
            self.radiator_kw = (
                float(zone_cfg[CONF_ZONE_RADIATOR_KW])
                if zone_cfg.get(CONF_ZONE_RADIATOR_KW) is not None
                else None
            )
        except (TypeError, ValueError):
            self.radiator_kw = None
        self.solar = SolarGain()
        self.co2 = Co2Guard()
        self.balance = BalanceMonitor()
        self._balance_store = None
        self._balance_samples_to_save = 0
        self._cap_last_ts: float | None = None
        self._valve_pct: float | None = None
        self._radiator_kw_est: float | None = None

        curve_coeff = coordinator.curve_coeff
        self.pid = PID(
            kp=PID_KP * max(0.5, min(curve_coeff, 2.0)),
            ki=PID_KI,
            kd=0.0,
            output_min=0.0,
            output_max=25.0,
            integral_clamp=PID_INTEGRAL_CLAMP,
        )
        self._pid_output: float = 0.0
        self._demand: float = 0.0

    def rescale_pid_for_curve(self, curve_coeff: float) -> None:
        """Re-scale the zone PID gain when auto-tune changes the curve.

        The PID kp is derived from the curve coefficient; without this the
        flow PID component keeps the stale gain after the base curve moved.
        """
        self.pid.kp = PID_KP * max(0.5, min(float(curve_coeff), 2.0))

    def _can_write_state(self) -> bool:
        """False until HA has attached this entity (entity_id + platform).

        Calling async_write_ha_state() before that raises
        NoEntitySpecifiedError and aborts the whole climate platform —
        every room then disappears on the next config-entry reload.
        """
        return bool(
            self.hass is not None
            and getattr(self, "entity_id", None)
            and getattr(self, "platform", None) is not None
        )

    def _safe_write_ha_state(self) -> None:
        if self._can_write_state():
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        self.coordinator.register_zone(self)

        # Balance history + auto-cap cooldown survive reloads/updates —
        # losing 2 h of valve samples on every minor release reads as
        # "the system forgot everything" for no reason.
        self._balance_store = Store(
            self.hass, 1, f"{self._attr_unique_id}_balance"
        )
        try:
            bal = await self._balance_store.async_load()
        except Exception:  # noqa: BLE001 - storage never blocks setup
            bal = None
        if isinstance(bal, dict):
            try:
                cap_ts = bal.get("cap_last_ts")
                if cap_ts is not None:
                    self._cap_last_ts = float(cap_ts)
            except (TypeError, ValueError):
                self._cap_last_ts = None
            self.balance.from_state(bal.get("balance") or {})

        # Seed temperature now that hass + entity_id exist.
        if self._temp_sensor:
            st = self.hass.states.get(self._temp_sensor)
            if st is not None and st.state not in ("unknown", "unavailable"):
                try:
                    v = float(st.state)
                    if math.isfinite(v):
                        self._current_temp = v
                        self._temp_from_trv = False
                except (TypeError, ValueError):
                    pass
        else:
            self._refresh_temp_from_trv()
        # Seed humidity from the configured sensor or the TRV itself.
        self._refresh_humidity()
        # Restore the user's last target across entry reloads. Zone cfgs only
        # carry the creation-time setpoint, so without this ANY options
        # update / reload silently reset rooms to DEFAULT_ZONE_SETPOINT.
        try:
            last = await self.async_get_last_state()
        except Exception:  # noqa: BLE001 - never block setup on restore
            last = None
        if last is not None:
            prev = last.attributes.get(ATTR_TEMPERATURE)
            if prev is not None:
                try:
                    restored = float(prev)
                except (TypeError, ValueError):
                    restored = None
                if restored is not None and DEFAULT_MIN_ROOM_TEMP <= restored <= DEFAULT_MAX_ROOM_TEMP:
                    self._target_temp = restored
            # hvac mode survives reloads too
            mode = last.state
            if mode == "off":
                self._hvac_mode = HVACMode.OFF
            elif mode == "heat":
                self._hvac_mode = HVACMode.HEAT
            preset = last.attributes.get("preset_mode")
            if preset in ZONE_PRESETS:
                self._preset = preset

    async def _async_persist_balance(self) -> None:
        """Save balance history + cap cooldown so reloads/updates keep it."""
        if self._balance_store is None:
            return
        try:
            await self._balance_store.async_save({
                "version": 1,
                "cap_last_ts": self._cap_last_ts,
                "balance": self.balance.to_state(),
            })
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).debug(
                "balance save failed", exc_info=True
            )

    async def async_will_remove_from_hass(self) -> None:
        # Final flush: a 2-hour verdict in progress survives update/reload.
        await self._async_persist_balance()

    @property
    def current_temperature(self) -> float | None:
        return self._current_temp

    @property
    def target_temperature(self) -> float:
        return self._target_temp

    @property
    def hvac_mode(self) -> HVACMode:
        return self._hvac_mode

    @property
    def hvac_action(self) -> HVACAction:
        if self._hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        if self._demand > 0.05 and self.coordinator.flow_setpoint is not None:
            return HVACAction.HEATING
        return HVACAction.IDLE

    @property
    def preset_mode(self) -> str:
        return self._preset

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        lead = self.lead_time_s(
            to_comfort=self._preset in ("away", "eco")
        )
        dead = self._dead_time_s()
        return {
            "demand_level": round(self._demand, 3),
            "pid_flow_contribution": round(self._pid_output, 2),
            "window_open": self._window_open,
            "floor": self.floor,
            "heater_control": self.heater_control,
            "slope_window_detect": self._slope_detector is not None,
            "slope_window_active": (
                self._slope_detector.open if self._slope_detector else False
            ),
            "trv": self._trv_entity,
            "trv_climates": self._trv_climates,
            "temp_sensor": self._temp_sensor,
            "temp_source": (
                "external"
                if self._temp_sensor
                else ("trv" if self._trv_entity else "none")
            ),
            "effective_setpoint": self.effective_setpoint(),
            "preheat": bool(self._preheat_active),
            "preset_source": self._preset_source,
            # Tier 3/4
            "solar_gain": self.solar.active,
            "co2_ppm": (
                round(self.co2.ppm) if self.co2.ppm is not None else None
            ),
            "needs_ventilation": self.co2.needs_ventilation,
            "valve_pct": self._valve_pct,
            "balance": self.balance.report(),
            "radiator_kw": self.radiator_kw,
            "radiator_kw_est": self._radiator_kw_est,
            "dead_time_s": round(dead, 0) if dead is not None else None,
            "lead_time_s": round(lead, 0) if lead is not None else None,
            "warm_rate_cph": self._warm_rate_cph(),
            "humidity": self._humidity_pct,
            "humidity_source": (
                "external" if (self._humidity_sensor and self._humidity_pct is not None)
                else ("trv" if self._humidity_pct is not None else None)
            ),
        }

    def _align_preset_to_manual(self, v: float) -> None:
        """Manual target vs preset reconciliation (both directions).

        * A manual temperature that is DISTINCT from every preset's temp
          overrides the preset — the preset is dropped ("none") so the
          manual target becomes the effective setpoint.
        * A manual temperature that EQUALS a preset's temp (within a step)
          auto-selects that preset instead of hiding it.
        """
        temps = getattr(self.coordinator, "preset_temps", None)
        if not isinstance(temps, dict):
            temps = DEFAULT_PRESET_TEMPS
        matched = None
        for name in ("comfort", "eco", "away", "boost"):
            pt = temps.get(name)
            if pt is None:
                continue
            try:
                if abs(float(v) - float(pt)) <= 0.25:  # exact grid match
                    matched = name
                    break
            except (TypeError, ValueError):
                continue
        if matched is not None:
            if self._preset != matched:
                self._debug(
                    "trv", f"{self._zone_name()}: manual {v:.1f} °C == "
                    f"{matched} preset — {matched} selected"
                )
            self._preset = matched
        elif self._preset in ("comfort", "eco", "away", "boost"):
            self._debug(
                "trv", f"{self._zone_name()}: manual {v:.1f} °C overrides "
                f"{self._preset} preset → none"
            )
            self._preset = "none"
        self._preset_source = "user"  # sticky until the schedule window changes

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if ATTR_TEMPERATURE in kwargs:
            try:
                v = float(kwargs[ATTR_TEMPERATURE])
            except (TypeError, ValueError):
                v = None
            if v is not None:
                self._target_temp = min(
                    self._attr_max_temp, max(self._attr_min_temp, v)
                )
                # Manual target must actually rule (the preset must not
                # swallow it) — with the auto-align carve-out for the
                # calibration session's own boosted write.
                calib = getattr(self.coordinator, "calibration", None)
                in_calib = calib is not None and bool(calib.active()) and (
                    calib.active_zone == self._zone_name()
                )
                if not in_calib:
                    self._align_preset_to_manual(self._target_temp)
                    self._preset_source = "user"
                await self._push_setpoint_to_trv("manual set")
        self._safe_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        self._hvac_mode = hvac_mode
        if hvac_mode == HVACMode.OFF:
            self._demand = 0.0
            self._pid_output = 0.0
            self.pid.reset()
            await self._push_hvac_to_trv(HVACMode.OFF)
        else:
            await self._push_hvac_to_trv(HVACMode.HEAT, "user heat mode")
            await self._push_setpoint_to_trv("user heat mode")
        self._safe_write_ha_state()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        if preset_mode not in ZONE_PRESETS:
            return
        self._preset = preset_mode
        self._preset_source = "user"  # sticky until schedule window changes
        self._preheat_active = False
        await self._push_setpoint_to_trv(f"preset {preset_mode}")
        self._safe_write_ha_state()

    def apply_schedule_preset(self, preset_mode: str) -> bool:
        """Apply a timetable preset (sync). Returns True if the room changed."""
        if preset_mode not in ZONE_PRESETS:
            return False
        if self.heater_control == "manual":
            return False
        if self._preset == preset_mode and self._preset_source == "schedule":
            return False
        self._preset = preset_mode
        self._preset_source = "schedule"
        if preset_mode not in ("away", "eco"):
            self._preheat_active = False
        # Best-effort TRV push without awaiting (called from state listener).
        if self.hass is not None:
            try:
                self.hass.async_create_task(
                    self._push_setpoint_to_trv(f"schedule → {preset_mode}")
                )
            except Exception:  # noqa: BLE001
                pass
            try:
                self._safe_write_ha_state()
            except Exception:  # noqa: BLE001
                pass
        return True

    @property
    def temp_sensor_entity(self) -> str | None:
        return self._temp_sensor

    @property
    def trv_entity(self) -> str | None:
        return self._trv_entity

    @property
    def trv_entities(self) -> list[str]:
        return list(self._trv_climates)

    @property
    def window_sensor_entities(self) -> list[str]:
        return list(self._window_sensors)

    def _zone_name(self) -> str:
        return (
            getattr(self, "_attr_name", None)
            or getattr(self, "name", None)
            or "Room"
        )

    def _dead_time_s(self) -> float | None:
        estimator = getattr(self.coordinator, "deadtime", None)
        if estimator is None:
            return None
        return estimator.seconds_for(self._zone_name())

    def _warm_rate_cph(self) -> float | None:
        learner = getattr(self.coordinator, "setbacks", None)
        if learner is None:
            return None
        return learner.warm_rate_for(self._zone_name())

    def comfort_setpoint(self) -> float:
        """User target without setback offset (what we must hit after away/eco)."""
        return self._target_temp

    def lead_time_s(self, *, to_comfort: bool = False) -> float | None:
        """Estimated seconds of CH needed to close the current deficit.

        to_comfort=True measures against the bare target (ignores setback
        offset) — used by optimal-start while still on away/eco.
        """
        from .preheat import lead_seconds

        if self._current_temp is None:
            return None
        target = self.comfort_setpoint() if to_comfort else self.effective_setpoint()
        deficit = target - self._current_temp
        if deficit <= 0:
            return 0.0
        return lead_seconds(
            dead_s=self._dead_time_s(),
            warm_cph=self._warm_rate_cph(),
            deficit_c=deficit,
        )

    def effective_setpoint(self) -> float:
        """Active preset = ABSOLUTE target temperature (user-editable).

        No preset ("none") → the room heats at its own target. Away/eco:
        the preset temperature is the DEEPEST the room may drop, while the
        per-room learned offset raises the target for slow rooms (a leaky
        hall that recovers slowly gets a shallower setback so it can catch
        up in time — it never drops below the preset). The Tier 3 solar
        trim applies in every state.
        """
        solar = getattr(self, "solar", None)
        solar_off = solar.offset_contribution if solar is not None else 0.0
        temps = getattr(self.coordinator, "preset_temps", None)
        if not isinstance(temps, dict):
            temps = DEFAULT_PRESET_TEMPS

        if self._preset in ("away", "eco"):
            preset_t = float(temps.get(self._preset, self._target_temp))
            target = preset_t
            learner = getattr(self.coordinator, "setbacks", None)
            if learner is not None:
                fallback = preset_t - self.comfort_setpoint()
                learned = learner.offset_for(
                    self._zone_name(),
                    fallback=fallback,
                    dead_time_s=self._dead_time_s(),
                )
                target = max(preset_t, self.comfort_setpoint() + learned)
            # Optimal-start catch-up: drive to the comfort target instead.
            if self._preheat_active:
                return self.comfort_setpoint()
            return target + solar_off

        if self._preset in ("comfort", "boost") and self._preset in temps:
            return float(temps[self._preset]) + solar_off

        # "none" — the room's own target
        return self._target_temp + solar_off

    def _update_preheat(self) -> None:
        """Arm/disarm reactive pre-heat from dead-time + warm-rate model."""
        from .preheat import should_preheat

        if (
            self._hvac_mode != HVACMode.HEAT
            or self._window_open
            or self.heater_control == "manual"
            or self._preset not in ("away", "eco")
            or self._current_temp is None
        ):
            if self._preheat_active:
                self._preheat_active = False
            return
        deficit = self.comfort_setpoint() - self._current_temp
        want = should_preheat(
            in_setback=True,
            comfort_deficit_c=deficit,
            dead_s=self._dead_time_s(),
            warm_cph=self._warm_rate_cph(),
            already_preheating=self._preheat_active,
        )
        if want != self._preheat_active:
            self._preheat_active = want
            # Push the raised (arm) or restored (disarm) effective setpoint to
            # the TRV. Without this the boiler fires on the pre-heat demand
            # while the radiator valve stays shut at the setback temperature —
            # gas burnt, room not warmed.
            if self.hass is not None and self._trv_entity:
                try:
                    self.hass.async_create_task(self._push_setpoint_to_trv())
                except Exception:  # noqa: BLE001
                    pass
            if want:
                _LOGGER.info(
                    "%s: pre-heat on (deficit %.1f °C, lead ~%.0f min)",
                    self._attr_name,
                    deficit,
                    (self.lead_time_s(to_comfort=True) or 0.0) / 60.0,
                )
            else:
                _LOGGER.info("%s: pre-heat off", self._attr_name)

    def wants_heat(self) -> bool:
        if self._hvac_mode != HVACMode.HEAT or self._window_open:
            return False
        # Manual rooms never drive boiler demand — HCC observes only.
        if self.heater_control == "manual":
            return False
        self._update_preheat()
        # Prefer measured room error; fall back to TRV reporting heating.
        if self._current_temp is not None:
            return (self.effective_setpoint() - self._current_temp) > 0.1
        return self._trv_requests_heat()

    def demand_level(self) -> float:
        if not self.wants_heat():
            self._demand = 0.0
            return 0.0
        if self._current_temp is None:
            self._demand = 0.5 if self._trv_requests_heat() else 0.0
            return self._demand
        error = self.effective_setpoint() - self._current_temp
        self._demand = max(0.0, min(1.0, error / 3.0))
        return self._demand

    def pid_flow_contribution(self) -> float:
        if not self.wants_heat() or self._current_temp is None:
            if not self.wants_heat():
                self.pid.reset()
            self._pid_output = 0.0
            return 0.0
        error = self.effective_setpoint() - self._current_temp
        self._pid_output = self.pid.update(error)
        return self._pid_output

    def paused(self) -> bool:
        return self._window_open

    @callback
    def on_sensor_update(
        self, temperature: float | None, window_open: bool | None
    ) -> None:
        if temperature is not None:
            self._current_temp = temperature
            self._temp_from_trv = False
        learner = getattr(self.coordinator, "setbacks", None)
        if (
            learner is not None
            and temperature is not None
            and self._hvac_mode == HVACMode.HEAT
            and not self._window_open
        ):
            import time as _t

            try:
                # Freeze cool-down learning while optimal-start is actively
                # heating — rising temps must not look like a slower cool.
                learner.observe(
                    self._zone_name(),
                    _t.time(),
                    temperature,
                    self._preset,
                    heating_allowed=not self._preheat_active,
                )
            except Exception:  # noqa: BLE001
                _LOGGER.debug("setback observe failed", exc_info=True)
                pass
        # Bootstrap calibration: feed the active session, finish it when the
        # target gain is reached (restore + injection happen in the task).
        calibrator = getattr(self.coordinator, "calibration", None)
        if (
            calibrator is not None
            and temperature is not None
            and not self._window_open
        ):
            import time as _t

            try:
                result = calibrator.observe(self._zone_name(), _t.time(), temperature)
            except Exception:  # noqa: BLE001
                _LOGGER.debug("calibration observe failed", exc_info=True)
                result = None
            if result is not None and self.hass is not None:
                self.hass.async_create_task(
                    self.coordinator.finish_calibration(result)
                )
        # Dead-time stopwatch: samples are checked against the armed heat
        # start; a confirmed rise closes the measurement for this room.
        estimator = getattr(self.coordinator, "deadtime", None)
        if (
            estimator is not None
            and temperature is not None
            and not self._window_open
        ):
            import time as _t

            try:
                estimator.observe(self._zone_name(), _t.time(), temperature)
            except Exception:  # noqa: BLE001
                _LOGGER.debug("deadtime observe failed", exc_info=True)
                pass
        # Insulation score: samples inside genuine cool-down stretches
        # (setback phases) yield a weather-normalized loss factor per room.
        scorer = getattr(self.coordinator, "insulation", None)
        if (
            scorer is not None
            and learner is not None
            and temperature is not None
            and not self._window_open
        ):
            import time as _t

            try:
                outdoor = None
                getter = getattr(self.coordinator, "outdoor_temp", None)
                if callable(getter):
                    outdoor = getter()
                scorer.observe(
                    self._attr_name,
                    _t.time(),
                    temperature,
                    outdoor,
                    cooling=learner.in_cooling(self._zone_name()),
                )
            except Exception:  # noqa: BLE001
                _LOGGER.debug("insulation observe failed", exc_info=True)
                pass
        # Slope-based window detection (rooms without contact sensors):
        # a fast temperature drop trips the same pause a door sensor would.
        if self._slope_detector is not None and temperature is not None:
            import time as _t

            try:
                now_open = self._slope_detector.observe(_t.time(), temperature)
            except Exception:  # noqa: BLE001
                _LOGGER.debug("window-slope detect failed", exc_info=True)
                now_open = self._window_open
            if now_open != self._window_open:
                self._window_open = now_open
                if now_open:
                    self._invalidate_deadtime()
                    _LOGGER.info(
                        "%s: heat paused (suspected open window/door)",
                        self._attr_name,
                    )
                else:
                    _LOGGER.info(
                        "%s: temperature stable again — heating resumes",
                        self._attr_name,
                    )
        if window_open is not None:
            was_open = self._window_open
            self._window_open = window_open
            if window_open and not was_open:
                self._invalidate_deadtime()
        self._safe_write_ha_state()

    def _invalidate_deadtime(self) -> None:
        """Window just opened: a running dead-time stopwatch now measures
        open-air physics, not the heating system — discard it."""
        estimator = getattr(self.coordinator, "deadtime", None)
        if estimator is not None:
            try:
                estimator.invalidate(self._zone_name())
            except Exception:  # noqa: BLE001
                pass

    @callback
    def on_trv_update(self) -> None:
        """TRV state changed — refresh temp/humidity if we use the TRV."""
        if not self._temp_sensor:
            self._refresh_temp_from_trv()
        if not self._humidity_sensor:
            self._refresh_humidity()
        self._safe_write_ha_state()
        # setup-time safety lives in _trv_state(): it no-ops while hass is
        # None, so wire_zone_sensors() can call this before entities attach.

    # ── Tier 3/4 sensor feeds ────────────────────────────────────────────
    @callback
    def on_lux_update(self, lux: float | None) -> None:
        """Lux sensor reading — feeds the solar-gain detector."""
        self.solar.update(lux)
        self._safe_write_ha_state()

    @callback
    def on_co2_update(self, ppm: float | None) -> None:
        """CO₂ sensor reading — feeds the ventilation flag."""
        self.co2.update(ppm)
        self._safe_write_ha_state()

    @callback
    def on_valve_update(self, pct: float | None) -> None:
        """TRV valve position 0–100 — feeds the balance monitor."""
        if pct is None:
            return
        try:
            self._valve_pct = max(0.0, min(100.0, float(pct)))
        except (TypeError, ValueError):
            return
        # Valve-open action for the debug screen: log meaningful moves
        # (≥1% change) so the log shows when a valve opened/closed by how much.
        prev = getattr(self, "_valve_pct_dbg", None)
        if prev is None or abs(self._valve_pct - prev) >= 1.0:
            self._valve_pct_dbg = self._valve_pct
            self._debug(
                "valve",
                f"{self._zone_name()}: valve {'opened' if (prev is None or self._valve_pct > prev) else 'closed'}"
                f" → {self._valve_pct:.0f}%",
            )
        below = (
            self._current_temp is not None
            and self.effective_setpoint() - self._current_temp > 0.1
        )
        self.balance.sample(self._valve_pct, below)
        self._balance_samples_to_save += 1
        if self._balance_samples_to_save >= 15 and self.hass is not None:
            self._balance_samples_to_save = 0
            self.hass.async_create_task(self._async_persist_balance())
        self._safe_write_ha_state()

    def _refresh_temp_from_trv(self) -> None:
        temp = self._trv_current_temp()
        if temp is not None:
            self._current_temp = temp
            self._temp_from_trv = True

    def valve_direct_active(self) -> bool:
        """True when HCC drives this room's valve opening degree directly.

        Requires the valve-direct heat mode AND a writable (number.*) valve
        position entity; sensor-only positions stay read-only.
        """
        return self.heater_control == HEAT_CONTROL_VALVE and (
            self._trv_position_entity or ""
        ).startswith("number.")

    def valve_want_pct(self) -> float:
        """Desired valve opening (0-100) from the room's live demand.

        Closed loop: demand_level() is the clamped comfort error / 3 °C, so
        ~33 % demand ≈ 1 °C deficit. The +10 headroom pushes the valve past
        proportional so a stubborn room actually reaches setpoint. Zero
        demand shuts fully — no smoulder into an already-warm room.
        """
        demand = self.demand_level()
        if demand > VALVE_OPEN_DEMAND:
            pct = max(VALVE_MIN_PCT, round(demand * 100.0))
            return min(100.0, float(pct + 10.0))
        return 0.0

    def valve_current_pct(self, hass) -> float | None:
        st = hass.states.get(self._trv_position_entity)
        if st is None:
            return None
        try:
            v = float(st.state)
        except (TypeError, ValueError):
            return None
        return max(0.0, min(100.0, v))

    def valve_apply(self, now: float, hass) -> None:
        """One tick of the valve-direct closed loop (rate-limited)."""
        if not self.valve_direct_active() or self._hvac_mode != HVACMode.HEAT:
            return
        want = self.valve_want_pct()
        cur = self.valve_current_pct(hass)
        if cur is None:
            return
        if self._window_open or self._hvac_mode != HVACMode.HEAT:
            want = 0.0  # paused: shut the valve regardless of demand
        if (
            abs(want - cur) < VALVE_HYST_PCT
            or now - self._valve_last_write < VALVE_WRITE_INTERVAL_S
        ):
            return
        self._valve_last_write = now
        self.hass.async_create_task(hass.services.async_call(
            "number", "set_value",
            {"entity_id": self._trv_position_entity, "value": want},
            blocking=False,
        ))
        self._debug(
            "valve-drive",
            f"{self._zone_name()}: valve → {want:.0f}% (was {cur:.0f}%, "
            f"demand {self.demand_level():.2f})",
        )

    async def force_valve_exercise(self) -> None:
        """Manual 'run valve maintenance now' action (panel button/WS)."""
        import time as _t

        self._valve_last_exercise = 0.0
        self._valve_last_exercise = _t.time()
        await self.valve_exercise()

    async def maybe_exercise(self, now: float = None) -> None:
        """Cheap per-tick entry: run valve_exercise only when the 7-day
        anti-stick clock is due and the room is idle."""
        if not self.valve_direct_active() or self._valve_exercising:
            return
        import time as _t

        if _t.time() - self._valve_last_exercise < 7 * 86400.0:
            return
        # Don't even build the task while heating demand is active.
        if self._hvac_mode != HVACMode.HEAT or self.wants_heat():
            return
        self._valve_last_exercise = _t.time()         # start the cooldown
        self.hass.async_create_task(self.valve_exercise())

    async def _exercise_sleep(self, seconds: float) -> None:
        await __import__("asyncio").sleep(seconds)

    async def valve_exercise(self) -> None:
        """Anti-stick valve exercise: a full travel sweep (min -> max -> min)
        while heating is IDLE -- that is exactly when mechanical valves
        seize. Returns the valve to the drive position afterwards, and
        suspends the drive loop for the duration so nothing fights the sweep.
        Rate-limited to one run per 7 days per room."""
        if not self.valve_direct_active() or self._valve_exercising:
            return
        # Never fight active heating: only exercise while the room is idle.
        if self._hvac_mode != HVACMode.HEAT or self.wants_heat():
            return
        import asyncio
        import time as _t

        if _t.time() - self._valve_last_exercise < 7 * 86400.0:
            return
        self._valve_exercising = True
        self._valve_last_exercise = _t.time()
        saved = self.valve_current_pct(self._hass)
        restore = float(saved) if saved is not None else 0.0
        steps = ((100.0, 45.0), (0.0, 45.0), (restore, 0.0))
        try:
            for step, wait in steps:
                await self._hass.services.async_call(
                    "number", "set_value",
                    {"entity_id": self._trv_position_entity, "value": step},
                    blocking=False,
                )
                self._debug(
                    "valve-drive",
                    f"{self._zone_name()}: exercising valve to {step:.0f}% (anti-stick)",
                )
                if wait:
                    await self._exercise_sleep(wait)
        finally:
            self._valve_exercising = False
            self._valve_last_write = _t.monotonic()  # restart the rate window
            self._debug(
                "valve-drive",
                f"{self._zone_name()}: valve exercise done (back to {restore:.0f}%)",
            )
    async def valve_pin_tick(self, now: float) -> None:
        """Keep the physical TRV out of its own algorithm's way: force heat
        mode and pin the target so the onboard curve does not close the valve
        while HCC is driving it (rate-limited)."""
        if not self.valve_direct_active() or self._hvac_mode != HVACMode.HEAT:
            return
        if now - self._valve_pin_at < VALVE_PIN_INTERVAL_S:
            return
        st = self._hass.states.get(self._trv_entity) if self._hass else None
        if st is None:
            return
        mode_ok = getattr(st, "state", None) == str(
            getattr(HVACMode, "HEAT", None)
        )
        cur_sp = (st.attributes or {}).get("temperature") if st.attributes else None
        want_sp = self.effective_setpoint()
        try:
            want_sp = round(float(want_sp), 1)
        except (TypeError, ValueError):
            want_sp = None
        if mode_ok and isinstance(cur_sp, (int, float)) and (
            abs(float(cur_sp) - want_sp) < 0.6
        ):
            self._valve_pin_at = now  # healthy pin: refresh the clock only
            return
        self._valve_pin_at = now
        if not mode_ok:
            await self._push_hvac_to_trv(
                HVACMode.HEAT, "valve-mode re-assert"
            )
        if isinstance(want_sp, (int, float)):
            await self.hass.services.async_call(
                "climate", "set_temperature",
                {"entity_id": self._trv_entity, "temperature": want_sp},
                blocking=False,
            )
            self._debug(
                "valve-drive",
                f"{self._zone_name()}: TRV pinned to heat/{want_sp:.1f} °C",
            )

    def _trv_humidity(self) -> float | None:
        st = self._trv_state()
        if st is None:
            return None
        raw = st.attributes.get("current_humidity")
        if raw is None:
            return None
        try:
            pct = float(raw)
        except (TypeError, ValueError):
            return None
        if not 0.0 <= pct <= 100.0:
            return None
        return pct

    def _refresh_humidity(self) -> None:
        """External RH if configured; otherwise the TRV's own sensor."""
        if self._humidity_sensor and self.hass is not None:
            st = self.hass.states.get(self._humidity_sensor)
            if st is not None and st.state not in ("unknown", "unavailable"):
                try:
                    pct = float(st.state)
                except (TypeError, ValueError):
                    pct = None
                if pct is not None and 0.0 <= pct <= 100.0:
                    self._humidity_pct = pct
                    self._humidity_from_trv = False
                    return
        elif not self._humidity_sensor:
            th = self._trv_humidity()
            if th is not None:
                self._humidity_pct = th
                self._humidity_from_trv = True

    @callback
    def on_humidity_update(self, pct: float | None) -> None:
        """External humidity sensor reading (RH %)."""
        if pct is None:
            return
        try:
            v = float(pct)
        except (TypeError, ValueError):
            return
        if not 0.0 <= v <= 100.0:
            return
        self._humidity_pct = v
        self._humidity_from_trv = False
        self._safe_write_ha_state()

    @property
    def current_humidity(self) -> float | None:
        return self._humidity_pct

    def humidity_sensor_entity(self) -> str | None:
        return self._humidity_sensor

    def _trv_state(self):
        # During platform setup wire_zone_sensors() can call us before the
        # entity is attached to hass — the classic crash is 'NoneType' object
        # has no attribute 'states', which aborts the whole climate platform
        # and unregisters every room (people see "all rooms disappeared").
        if not self._trv_entity or self.hass is None:
            return None
        return self.hass.states.get(self._trv_entity)

    def _trv_current_temp(self) -> float | None:
        st = self._trv_state()
        if st is None:
            return None
        raw = st.attributes.get("current_temperature")
        if raw is None:
            return None
        try:
            v = float(raw)
        except (TypeError, ValueError):
            return None
        return v if math.isfinite(v) else None

    def _trv_requests_heat(self) -> bool:
        st = self._trv_state()
        if st is None:
            return False
        action = st.attributes.get("hvac_action")
        if action == "heating":
            return True
        # Some TRVs only expose mode + current/target temps.
        cur = self._trv_current_temp()
        try:
            target = float(st.attributes.get("temperature"))
            if not math.isfinite(target):
                target = None
        except (TypeError, ValueError):
            target = None
        if cur is not None and target is not None:
            return (target - cur) > 0.1 and st.state not in ("off", "unavailable")
        return st.state == "heat"

    def _debug(self, kind: str, text: str) -> None:
        log = getattr(self.coordinator, "debug_log", None)
        if callable(log):
            try:
                log(kind, text)
            except Exception:  # noqa: BLE001
                pass

    async def _push_setpoint_to_trv(self, reason: str = "") -> None:
        if not self._trv_entity or self.heater_control == "manual":
            return
        try:
            sp = self.effective_setpoint()
            # No-op suppression: skip re-sends of values the TRV already
            # holds, compared ON ITS OWN rounding grid (0.5/1.0 °C). Every
            # avoided push saves a zigbee write + a motor wake.
            st = self._trv_state()
            if st is not None:
                try:
                    step = float((st.attributes or {}).get("target_temp_step", 0.5))
                except (TypeError, ValueError):
                    step = 0.5
                live = (st.attributes or {}).get("temperature")
                if (
                    isinstance(live, (int, float))
                    and step > 0
                    and sp - float(live) < step * 0.9
                ):
                    _LOGGER.debug(
                        "%s: TRV already at %.2f (grid %.2f), skip push",
                        self._zone_name(), float(live), step,
                    )
                    return
            await self.hass.services.async_call(
                "climate",
                "set_temperature",
                {
                    "entity_id": self._trv_entity,
                    "temperature": sp,
                },
                blocking=False,
            )
            # Real TRV action for the debug screen: room + target + trigger.
            valve = (
                f", valve {self._valve_pct:.0f}%"
                if isinstance(self._valve_pct, (int, float))
                else ""
            )
            self._debug(
                "trv",
                f"{self._zone_name()}: TRV {self._trv_entity} target → "
                f"{sp:.1f} °C{valve}"
                + (f" ({reason})" if reason else ""),
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug("TRV setpoint push failed for %s", self._trv_entity)

    async def _push_hvac_to_trv(self, mode: HVACMode, reason: str = "") -> None:
        if not self._trv_entity or self.heater_control == "manual":
            return
        try:
            st = self._trv_state()
            if st is not None and str(st.state or "").lower() == str(mode).lower():
                return  # already there
            await self.hass.services.async_call(
                "climate",
                "set_hvac_mode",
                {"entity_id": self._trv_entity, "hvac_mode": mode},
                blocking=False,
            )
            self._debug(
                "trv",
                f"{self._zone_name()}: TRV {self._trv_entity} mode → "
                f"{str(mode).upper()}"
                + (f" ({reason})" if reason else ""),
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug("TRV mode push failed for %s", self._trv_entity)
