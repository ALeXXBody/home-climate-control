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

from .const import (
    CONF_ZONE_CO2_SENSOR,
    CONF_ZONE_LUX_SENSOR,
    CONF_ZONE_RADIATOR_KW,
    CONF_ZONE_TRV_POSITION,
    DEFAULT_MAX_ROOM_TEMP,
    DEFAULT_MIN_ROOM_TEMP,
    DEFAULT_TARGET_STEP,
    DEFAULT_ZONE_SETPOINT,
    PID_INTEGRAL_CLAMP,
    PID_KI,
    PID_KP,
    PRESET_OFFSETS,
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
        self.heater_control: str = control if control in ("smart", "manual") else "smart"
        # Rooms without physical sensors get slope-based detection instead:
        # an abnormally fast temperature drop pauses heat just like a
        # tripped door sensor would.
        self._slope_detector = (
            None if self._window_sensors else SlopeWindowDetector()
        )

        start = zone_cfg.get("demo_start_temp")
        self._current_temp: float | None = float(start) if start is not None else None
        self._target_temp: float = float(zone_cfg.get("setpoint", DEFAULT_ZONE_SETPOINT))
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

    async def async_added_to_hass(self) -> None:
        self.coordinator.register_zone(self)
        # Seed temperature from TRV when no external sensor is configured.
        if not self._temp_sensor:
            self._refresh_temp_from_trv()
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
        }

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if ATTR_TEMPERATURE in kwargs:
            self._target_temp = float(kwargs[ATTR_TEMPERATURE])
            await self._push_setpoint_to_trv()
        self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        self._hvac_mode = hvac_mode
        if hvac_mode == HVACMode.OFF:
            self._demand = 0.0
            self._pid_output = 0.0
            self.pid.reset()
            await self._push_hvac_to_trv(HVACMode.OFF)
        else:
            await self._push_hvac_to_trv(HVACMode.HEAT)
            await self._push_setpoint_to_trv()
        self.async_write_ha_state()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        if preset_mode not in ZONE_PRESETS:
            return
        self._preset = preset_mode
        self._preset_source = "user"  # sticky until schedule window changes
        self._preheat_active = False
        await self._push_setpoint_to_trv()
        self.async_write_ha_state()

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
                self.hass.async_create_task(self._push_setpoint_to_trv())
            except Exception:  # noqa: BLE001
                pass
            try:
                self.async_write_ha_state()
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
        offset = PRESET_OFFSETS.get(self._preset, 0.0)
        learner = getattr(self.coordinator, "setbacks", None)
        if learner is not None and self._preset in ("away", "eco"):
            offset = learner.offset_for(
                self._zone_name(),
                fallback=offset,
                dead_time_s=self._dead_time_s(),
            )
        # Tier 3 solar gain: a sun-warmed room is comfortable slightly
        # cooler — shave the comfort target while direct sun holds.
        # Only on comfort-side presets so setback learning stays untouched.
        if self._preset not in ("away", "eco"):
            offset += self.solar.offset_contribution
        # Optimal-start catch-up: while pre-heating out of a setback, drive
        # the room toward the comfort target (not the lowered night SP).
        if self._preheat_active and self._preset in ("away", "eco"):
            return self.comfort_setpoint()
        return self._target_temp + offset

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
                pass
        # Slope-based window detection (rooms without contact sensors):
        # a fast temperature drop trips the same pause a door sensor would.
        if self._slope_detector is not None and temperature is not None:
            import time as _t

            try:
                now_open = self._slope_detector.observe(_t.time(), temperature)
            except Exception:  # noqa: BLE001
                now_open = self._window_open
            if now_open != self._window_open:
                self._window_open = now_open
                if now_open:
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
            self._window_open = window_open
        if self.hass is not None:
            self.async_write_ha_state()

    @callback
    def on_trv_update(self) -> None:
        """TRV state changed — refresh temp if we use TRV as sensor."""
        if not self._temp_sensor:
            self._refresh_temp_from_trv()
        if self.hass is not None:
            self.async_write_ha_state()

    # ── Tier 3/4 sensor feeds ────────────────────────────────────────────
    @callback
    def on_lux_update(self, lux: float | None) -> None:
        """Lux sensor reading — feeds the solar-gain detector."""
        self.solar.update(lux)
        if self.hass is not None:
            self.async_write_ha_state()

    @callback
    def on_co2_update(self, ppm: float | None) -> None:
        """CO₂ sensor reading — feeds the ventilation flag."""
        self.co2.update(ppm)
        if self.hass is not None:
            self.async_write_ha_state()

    @callback
    def on_valve_update(self, pct: float | None) -> None:
        """TRV valve position 0–100 — feeds the balance monitor."""
        if pct is None:
            return
        try:
            self._valve_pct = max(0.0, min(100.0, float(pct)))
        except (TypeError, ValueError):
            return
        below = (
            self._current_temp is not None
            and self.effective_setpoint() - self._current_temp > 0.1
        )
        self.balance.sample(self._valve_pct, below)
        if self.hass is not None:
            self.async_write_ha_state()

    def _refresh_temp_from_trv(self) -> None:
        temp = self._trv_current_temp()
        if temp is not None:
            self._current_temp = temp
            self._temp_from_trv = True

    def _trv_state(self):
        if not self._trv_entity:
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
            return float(raw)
        except (TypeError, ValueError):
            return None

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
        except (TypeError, ValueError):
            target = None
        if cur is not None and target is not None:
            return (target - cur) > 0.1 and st.state not in ("off", "unavailable")
        return st.state == "heat"

    async def _push_setpoint_to_trv(self) -> None:
        if not self._trv_entity or self.heater_control == "manual":
            return
        try:
            await self.hass.services.async_call(
                "climate",
                "set_temperature",
                {
                    "entity_id": self._trv_entity,
                    "temperature": self.effective_setpoint(),
                },
                blocking=False,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug("TRV setpoint push failed for %s", self._trv_entity)

    async def _push_hvac_to_trv(self, mode: HVACMode) -> None:
        if not self._trv_entity or self.heater_control == "manual":
            return
        try:
            await self.hass.services.async_call(
                "climate",
                "set_hvac_mode",
                {"entity_id": self._trv_entity, "hvac_mode": mode},
                blocking=False,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug("TRV mode push failed for %s", self._trv_entity)
