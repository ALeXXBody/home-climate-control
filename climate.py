"""Home Assistant custom component for Home Climate System with enhanced PID control."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_TEMPERATURE,
    CONF_NAME,
    PRECISION_HALVES,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DEFAULT_BOILER_STATE,
    DEFAULT_HVAC_MODES,
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_TEMP,
    DEFAULT_NAME,
    DEFAULT_PRESET_MODES,
    DOMAIN,
)
from .coordinator import HomeClimateSystemCoordinator

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the climate platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    
    async_add_entities([HomeClimateSystemEntity(coordinator, entry)], True)


class HomeClimateSystemEntity(ClimateEntity):
    """Representation of a Home Climate System entity."""

    def __init__(
        self,
        coordinator: HomeClimateSystemCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the climate device."""
        self.coordinator = coordinator
        self._config_entry = config_entry
        
        # Get configuration from entry or use defaults
        name = config_entry.data.get(CONF_NAME, DEFAULT_NAME)
        
        self._attr_name = name
        self._attr_unique_id = f"{config_entry.entry_id}_{name}"
        
        # Set supported features
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE |
            ClimateEntityFeature.PRESET_MODE
        )
        
        # Temperature settings
        self._attr_min_temp = DEFAULT_MIN_TEMP
        self._attr_max_temp = DEFAULT_MAX_TEMP
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_precision = PRECISION_HALVES
        
        # HVAC modes and presets
        self._attr_hvac_modes = DEFAULT_HVAC_MODES
        self._attr_preset_modes = DEFAULT_PRESET_MODES
        
        # Initialize state variables
        self._current_temperature: Optional[float] = None
        self._target_temperature: float = 20.0
        self._hvac_mode: HVACMode = HVACMode.OFF
        self._preset_mode: str = "none"
        
        # Boiler control parameters
        self._boiler_state: bool = DEFAULT_BOILER_STATE
        
        # PID controller variables (enhanced)
        self._pid_kp = 2.0      # Proportional gain - increased for faster response
        self._pid_ki = 0.5      # Integral gain - reduced to prevent overshoot
        self._pid_kd = 1.0      # Derivative gain - added for stability
        
        # PID integral term accumulator and previous error
        self._integral = 0.0
        self._previous_error = 0.0
        self._previous_time = None
        
        # Control parameters
        self._modulation_level: float = 0.0     # Percentage (0-100)
        
    @property
    def current_temperature(self) -> Optional[float]:
        """Return the current temperature."""
        return self.coordinator.current_temperature
    
    @property
    def target_temperature(self) -> float:
        """Return the target temperature."""
        return self._target_temperature
    
    @property
    def hvac_mode(self) -> HVACMode:
        """Return the current HVAC mode."""
        return self._hvac_mode
    
    @property
    def preset_mode(self) -> str:
        """Return the current preset mode."""
        return self._preset_mode
    
    @property
    def boiler_state(self) -> bool:
        """Return the current boiler state."""
        return self._boiler_state

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        if ATTR_TEMPERATURE in kwargs:
            self._target_temperature = float(kwargs[ATTR_TEMPERATURE])
            
        # Update coordinator with new setpoint
        await self.coordinator.async_update_target_temp(
            self._target_temperature,
            self._preset_mode
        )
        
        # Trigger update to recalculate control logic
        await self.coordinator.async_refresh()
    
    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        if hvac_mode not in DEFAULT_HVAC_MODES:
            return
            
        self._hvac_mode = hvac_mode
        
        # Update coordinator with new mode
        await self.coordinator.async_update_hvac_mode(hvac_mode)
        
        # Trigger update to recalculate control logic
        await self.coordinator.async_refresh()
    
    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new target preset mode."""
        if preset_mode not in DEFAULT_PRESET_MODES:
            return
            
        self._preset_mode = preset_mode
        
        # Update coordinator with new preset
        await self.coordinator.async_update_preset(preset_mode)
        
        # Trigger update to recalculate control logic
        await self.coordinator.async_refresh()
    
    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if not self.available:
            return
            
        # Update internal state with new values from coordinator
        self._current_temperature = self.coordinator.current_temperature
        
        # Recalculate control logic based on current conditions and presets
        self._calculate_pid_control()
        
        # Update boiler state based on modulation level
        self._boiler_state = bool(self._modulation_level > 0)
        
        # Notify Home Assistant of the update
        self.async_write_ha_state()

    def _calculate_pid_control(self) -> None:
        """Calculate enhanced PID control for boiler modulation."""
        if self._current_temperature is None or self._target_temperature is None:
            return
            
        # Calculate error (difference between target and current temperature)
        error = self._target_temperature - self._current_temperature
        
        # Get current time for delta calculation
        import time
        current_time = time.time()
        
        if self._previous_time is not None:
            dt = current_time - self._previous_time
            
            # Proportional term (enhanced with preset-specific adjustments)
            proportional = error * self._pid_kp
            
            # Integral term with anti-windup protection
            self._integral += error * self._pid_ki * dt
            # Anti-windup: limit integral term to prevent overshoot
            max_integral = 10.0 if self._preset_mode == "boost" else 5.0
            self._integral = max(-max_integral, min(max_integral, self._integral))
            
            # Derivative term (enhanced with smoothing)
            derivative = (
                (error - self._previous_error) / dt 
                if dt > 0 
                else 0
            )
            derivative *= self._pid_kd
            
            # Calculate PID output
            pid_output = proportional + self._integral + derivative
            
            # Apply preset-specific adjustments to control logic
            if self._preset_mode == "boost":
                # Boost mode: higher modulation for faster heating
                pid_output *= 1.5
            elif self._preset_mode == "away":
                # Away mode: reduce modulation significantly 
                pid_output *= 0.3
                
            # Convert to modulation level (0-100%)
            self._modulation_level = max(0, min(100, pid_output))
            
        else:
            # First calculation - initialize integral term
            self._integral = error * self._pid_ki
            
        # Update previous values for next iteration
        self._previous_error = error
        self._previous_time = current_time
        
    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        await super().async_added_to_hass()
        
        # Register to receive updates from coordinator
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )