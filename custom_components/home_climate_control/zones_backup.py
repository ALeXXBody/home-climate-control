"""Zone-config backup — the safety net for the room list.

The room list lives in `options["zones"]` on the config entry. Every write
path (add/remove/rename room, options flow, set_options) replaces that list
wholesale. Any bad write — a stale client, a race, a bug — erases every
room with no recovery path.

This module keeps a copy of the last known-good zone list in its own HA
Store. On entry setup, if options have no zones but the backup does, the
rooms are restored automatically (logged, never silent).

Storage: home_climate_control_zones_backup, version 1.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = "home_climate_control_zones_backup"
STORAGE_VERSION = 1


class ZonesBackup:
    """Last-known-good copy of the zone list, stored independently of options."""

    def __init__(self, hass) -> None:
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY) if hass else None

    async def async_load(self) -> list[dict[str, Any]] | None:
        """Returns the backed-up zone list, or None when no backup exists."""
        if self._store is None:
            return None
        try:
            data = await self._store.async_load() or {}
        except Exception:  # noqa: BLE001 - storage never blocks setup
            return None
        zones = data.get("zones")
        if isinstance(zones, list) and zones:
            return zones
        return None

    async def async_save(self, zones: list[dict[str, Any]]) -> None:
        """Persist a copy of the zone list (called after every successful write)."""
        if self._store is None or not zones:
            return
        try:
            await self._store.async_save({"version": 1, "zones": zones})
            _LOGGER.debug("Zones backup saved: %d rooms", len(zones))
        except Exception:  # noqa: BLE001
            _LOGGER.debug("zones backup save failed", exc_info=True)

    def save(self, zones: list[dict[str, Any]], hass) -> None:
        """Fire-and-forget save from a sync WS handler context."""
        if hass is None:
            return
        hass.async_create_task(self.async_save(zones))
