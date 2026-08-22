"""Coordinator for Home Climate System."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Dict, Optional

from homeassistant.components.climate import HVACMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import UPDATE_INTERVAL_SECONDS

_LOGGER = logging.getLogger(__name__)


class HomeClimateSystemCoordinator(DataUpdateCoordinator):
    """Home Climate System data update coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        name: str,
        current_temperature: Optional[float] = None,
        target_temperature: float = 20.0,
        hvac_mode: HVACMode = HVACMode.OFF,
        preset_mode: str = "none",
    ) -> None:
        """Initialize the coordinator."""
        self._current_temperature = current_temperature
        self._target_temperature = target_temperature
        self._hvac_mode = hvac_mode
        self._preset_mode = preset_mode
        
        super().__init__(
            hass,
            _LOGGER,
            name=name,
            update_interval=timedelta(seconds=UPDATE_INTERVAL_SECONDS),
        )

    @property
    def current_temperature(self) -> Optional[float]:
        """Return the current temperature."""
        return self._current_temperature

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

    async def _async_update_data(self) -> Dict[str, Any]:
        """Fetch data from sensors and update internal state."""
        try:
            # This is where you would typically fetch real sensor data
            # For now we'll simulate it or use stored values
            
            # In a real implementation, this might involve:
            # 1. Reading temperature from configured sensor entity
            # 2. Updating target based on preset mode logic  
            # 3. Calculating boiler state using PID control
            
            data = {
                "current_temperature": self._current_temperature,
                "target_temperature": self._target_temperature,
                "hvac_mode": self._hvac_mode, 
                "preset_mode": self._preset_mode
            }
            
            return data
            
        except Exception as err:
            raise UpdateFailed(f"Error updating Home Climate System: {err}")

    def update_current_temp(self, temperature: float) -> None:
        """Update the current temperature."""
        self._current_temperature = temperature
        
    async def async_update_target_temp(
        self,
        target_temp: float,
        preset_mode: str
    ) -> None:
        """Update the target temperature with preset logic.""" 
        # Apply preset-specific adjustments to target temp
        if preset_mode == "away":
            target_temp -= 3.0   # Lower by 3 degrees in away mode
        elif preset_mode == "boost":  
            target_temp += 2.0   # Raise by 2 degrees in boost mode
            
        self._target_temperature = target_temp
        
    async def async_update_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Update the HVAC mode."""
        self._hvac_mode = hvac_mode
        
    async def async_update_preset(self, preset_mode: str) -> None:
        """Update the preset mode.""" 
        # Apply preset-specific adjustments to target temp
        if preset_mode == "away":
            self._target_temperature -= 3.0   # Lower by 3 degrees in away mode
        elif preset_mode == "boost":  
            self._target_temperature += 2.0   # Raise by 2 degrees in boost mode
            
        self._preset_mode = preset_mode