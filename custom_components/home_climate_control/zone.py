"""ZoneClimateEntity: the climate entity HCC creates per room/zone.

A zone owns:
- an authoritative room temperature sensor,
- optional TRV climate entities whose requests are *respected*: their
  setpoint/hvac_action feed demand instead of being fought,
- optional window sensors that pause heating when open,
- a PID producing °C of flow-temperature contribution.
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

from .const import (
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
from .pid import PID

_LOGGER = logging.getLogger(__name__)


class ZoneClimateEntity(ClimateEntity):
    """One heating zone. Reports demand to the CentralController."""

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
        self._attr_unique_id = f"{entry.entry_id}_zone_{name}"
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_precision = PRECISION_HALVES
        self._attr_min_temp = DEFAULT_MIN_ROOM_TEMP
        self._attr_max_temp = DEFAULT_MAX_ROOM_TEMP
        self._attr_target_temperature_step = DEFAULT_TARGET_STEP
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
        )

        self._temp_sensor = zone_cfg.get("temp_sensor")
        self._window_sensors: list[str] = list(zone_cfg.get("window_sensors") or [])
        self._trv_climates: list[str] = list(zone_cfg.get("trv_climates") or [])

        self._current_temp: float | None = None
        self._target_temp: float = float(zone_cfg.get("setpoint", DEFAULT_ZONE_SETPOINT))
        self._preset: str = "none"
        self._hvac_mode: HVACMode = HVACMode.OFF
        self._window_open: bool = False

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
        return {
            "demand_level": round(self._demand, 3),
            "pid_flow_contribution": round(self._pid_output, 2),
            "window_open": self._window_open,
            "trv_climates": self._trv_climates,
            "trv_requests_heat": self._trv_requests_heat(),
            "effective_setpoint": self.effective_setpoint(),
        }

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if ATTR_TEMPERATURE in kwargs:
            self._target_temp = float(kwargs[ATTR_TEMPERATURE])
        self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        self._hvac_mode = hvac_mode
        if hvac_mode == HVACMode.OFF:
            self._demand = 0.0
            self._pid_output = 0.0
            self.pid.reset()
        self.async_write_ha_state()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        if preset_mode not in ZONE_PRESETS:
            return
        self._preset = preset_mode
        self.async_write_ha_state()

    @property
    def temp_sensor_entity(self) -> str | None:
        return self._temp_sensor

    @property
    def window_sensor_entities(self) -> list[str]:
        return list(self._window_sensors)

    def effective_setpoint(self) -> float:
        offset = PRESET_OFFSETS.get(self._preset, 0.0)
        base = self._target_temp + offset
        trv_max = self._max_trv_setpoint()
        if trv_max is not None:
            return max(base, trv_max)
        return base

    def wants_heat(self) -> bool:
        if self._hvac_mode != HVACMode.HEAT or self._window_open:
            return False
        if self._current_temp is None:
            # Still respect TRVs even if room sensor is missing.
            return self._trv_requests_heat()
        return (self.effective_setpoint() - self._current_temp) > 0.1 or self._trv_requests_heat()

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
        if self._current_temp is None:
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
        if window_open is not None:
            self._window_open = window_open
        if self.hass is not None:
            self.async_write_ha_state()

    def external_outdoor_temp(self) -> float | None:
        return None

    def _trv_states(self):
        for entity_id in self._trv_climates:
            st = self.hass.states.get(entity_id)
            if st is not None:
                yield st

    def _max_trv_setpoint(self) -> float | None:
        vals = []
        for st in self._trv_states():
            raw = st.attributes.get("temperature")
            if raw is None:
                continue
            try:
                vals.append(float(raw))
            except (TypeError, ValueError):
                continue
        return max(vals) if vals else None

    def _trv_requests_heat(self) -> bool:
        return any(
            st.attributes.get("hvac_action") == "heating" for st in self._trv_states()
        )
