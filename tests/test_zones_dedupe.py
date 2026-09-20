"""Zone deduplication — the fix for the 'rooms have empty data' incident.

Root cause: ws_add_zone validated against the CONTROLLER's in-memory zone
list. When the platform crashed (any of the 1.10.x setup bugs), the
controller was empty, so every add passed — including duplicates of rooms
already in options. The platform then created two entities with the same
unique_id; HA ignored the second (the one with the user's saved config);
the first (stale/empty) always won. Users saw: TRV/temp/floor never save,
rooms always show old values.
"""

from custom_components.home_climate_control import _dedupe_zones
from custom_components.home_climate_control.const import CONF_ZONES


def test_dedupe_keeps_last_wins():
    zones = [
        {"name": "Office", "trv_climates": [], "floor": 0},
        {"name": "Office", "trv_climates": ["climate.office_trv"], "floor": 1},
    ]
    result = _dedupe_zones(zones)
    assert len(result) == 1
    assert result[0]["trv_climates"] == ["climate.office_trv"]
    assert result[0]["floor"] == 1


def test_dedupe_no_duplicates_is_identity():
    zones = [
        {"name": "Office", "trv_climates": ["climate.office_trv"]},
        {"name": "Kitchen", "heat_control": "manual"},
    ]
    assert _dedupe_zones(zones) == zones


def test_dedupe_empty_and_none():
    assert _dedupe_zones([]) == []
    assert _dedupe_zones(None) == []
    assert _dedupe_zones([None, {}]) == []


def test_add_zone_rejects_duplicate_even_with_empty_controller():
    """The exact incident: platform crashed → controller empty → adds
    created duplicates in options. Now validates against OPTIONS."""
    import asyncio
    from unittest.mock import MagicMock
    from custom_components.home_climate_control import websocket_api

    entry = MagicMock()
    entry.entry_id = "e1"
    entry.options = {CONF_ZONES: [{"name": "Office",
                                   "trv_climates": ["climate.office_trv"]}]}
    controller = MagicMock()
    controller.zones = []  # empty controller — old code let duplicates through
    hass = MagicMock()
    hass.data = {websocket_api.DOMAIN: {"e1": {"controller": controller}}}
    hass.config_entries.async_get_entry = lambda eid: entry
    conn = MagicMock()

    asyncio.run(websocket_api.ws_add_zone(hass, conn, {
        "id": 1, "name": "Office", "heat_control": "smart", "floor": 0,
        "trv_climates": ["climate.office_trv"], "temp_sensor": "",
        "window_sensors": [],
    }))
    conn.send_error.assert_called_once()
    hass.config_entries.async_update_entry.assert_not_called()
