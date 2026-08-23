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


def _as_list(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


class ZoneClimateEntity(ClimateEntity):
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

        start = zone_cfg.get("demo_start_temp")
        self._current_temp: float | None = float(start) if start is not None else None
        self._target_temp: float = float(zone_cfg.get("setpoint", DEFAULT_ZONE_SETPOINT))
        self._preset: str = "none"
        self._hvac_mode: HVACMode = (
            HVACMode.HEAT if zone_cfg.get("demo_start_temp") is not None else HVACMode.OFF
        )
        self._window_open: bool = False
        self._temp_from_trv: bool = False

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
            "trv": self._trv_entity,
            "trv_climates": self._trv_climates,
            "temp_sensor": self._temp_sensor,
            "temp_source": (
                "external"
                if self._temp_sensor
                else ("trv" if self._trv_entity else "none")
            ),
            "effective_setpoint": self.effective_setpoint(),
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
        await self._push_setpoint_to_trv()
        self.async_write_ha_state()

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

    def effective_setpoint(self) -> float:
        offset = PRESET_OFFSETS.get(self._preset, 0.0)
        learner = getattr(self.coordinator, "setbacks", None)
        if learner is not None and self._preset in ("away", "eco"):
            offset = learner.offset_for(self.name, fallback=offset)
        return self._target_temp + offset

    def wants_heat(self) -> bool:
        if self._hvac_mode != HVACMode.HEAT or self._window_open:
            return False
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
                learner.observe(self.name, _t.time(), temperature, self._preset)
            except Exception:  # noqa: BLE001
                pass
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
        if not self._trv_entity:
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
        if not self._trv_entity:
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
