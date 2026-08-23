"""Climate platform for Home Climate Control: creates the zone entities."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import get_controller, wire_zone_sensors
from .const import DOMAIN
from .zone import ZoneClimateEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    stored = hass.data[DOMAIN][entry.entry_id]
    controller = get_controller(hass, entry)
    zones_cfg: list[dict] = stored.get("zones_cfg", [])

    entities = [ZoneClimateEntity(hass, controller, entry, zcfg) for zcfg in zones_cfg]
    if not entities:
        _LOGGER.warning(
            "No rooms configured for %s — add rooms via config or reinstall",
            entry.title,
        )

    async_add_entities(entities, update_before_add=False)
    # Wire external temp sensors + TRV climates (TRV temp is the fallback).
    # Demo rooms are driven by DemoBoilerBackend physics, not HA entities.
    if any(
        z.temp_sensor_entity or getattr(z, "trv_entity", None) for z in entities
    ):
        wire_zone_sensors(hass, entry, entities)
    await controller.async_start()
