"""Central heating mode driving every smart/valve room at once.

A single HA-native `select` entity ("Global heating mode") that pushes one
preset to all controllable rooms -- friendly for dashboard cards and for
"leaving → away everywhere" automations without opening the panel.
Auto restores schedule-driven presets.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

OPTIONS = ("auto", "comfort", "eco", "away", "boost")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    async_add_entities([CentralModeSelect(hass, entry.entry_id)])


class CentralModeSelect(SelectEntity):
    """Broadcast one preset to every controllable room."""

    _attr_should_poll = False
    _attr_name = "Global heating mode"
    _attr_icon = "mdi:thermostat-box"
    _attr_options = list(OPTIONS)
    _current_option = "auto"

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self.hass = hass
        self._entry_id = entry_id
        self._attr_unique_id = f"{DOMAIN}_central_mode_{entry_id}"

    def _zones(self) -> list:
        data = self.hass.data.get(DOMAIN, {}).get(self._entry_id, {})
        return getattr(data.get("controller"), "zones", None) or []

    async def async_select_option(self, option: str, **kwargs: Any) -> None:
        if option not in OPTIONS:
            return
        self._current_option = option
        tasks = []
        for z in self._zones():
            manual = getattr(z, "heater_control", "smart") == "manual"
            fn = getattr(z, "apply_schedule_preset" if option == "auto" else
                         "async_set_preset_mode", None)
            if fn is None or manual:
                continue
            if option == "auto":
                # Return control to the schedule listener per room.
                self.hass.async_create_task(
                    z.apply_schedule_preset(getattr(z, "_preset", "none"))
                )
            else:
                tasks.append(z.async_set_preset_mode(option))
        for t in tasks:
            self.hass.async_create_task(t)
        self._attr_current_option = option
        self.async_write_ha_state()
