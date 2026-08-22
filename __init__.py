"""Home Assistant custom component for Home Climate System."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import HomeClimateSystemCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the climate platform from a config entry."""
    
    # Create coordinator with default values
    coordinator = HomeClimateSystemCoordinator(
        hass=hass,
        name=entry.data.get("name", "Home Climate System"),
        current_temperature=None,
        target_temperature=20.0,
        hvac_mode="off",
        preset_mode="none"
    )
    
    # Store coordinator in hass data
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator
    
    # Set up climate platform 
    await hass.async_create_task(
        hass.config_entries.async_forward_entry_setups(entry, ["climate"])
    )
    
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, ["climate"])
    
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        
    return unload_ok