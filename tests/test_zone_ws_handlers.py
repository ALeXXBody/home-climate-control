"""Tests for zone WS handler race-condition fix.

After calling ws_rename_zone / ws_add_zone / ws_remove_zone, the status
returned to the frontend must reflect the updated config — not stale
in-memory entities.  The fix: ``await entry.async_reload()`` before
``_collect_status()``.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.home_climate_control.const import (
    CONF_ZONE_HEAT_CONTROL,
    CONF_ZONE_NAME,
    CONF_ZONES,
    DOMAIN,
)
from custom_components.home_climate_control.websocket_api import (
    ws_add_zone,
    ws_rename_zone,
    ws_remove_zone,
)

ENTRY_ID = "entry-hcc-1"


def _make_zone(name: str, heat_control: str = "smart"):
    """Create a minimal zone-like object that _collect_status reads."""
    return SimpleNamespace(
        name=name,
        entity_id=f"climate.{name.lower().replace(' ', '_')}",
        current_temperature=21.0,
        target_temperature=22.0,
        hvac_mode="heat",
        hvac_action="idle",
        preset_mode="none",
        demand_level=lambda: 0.5,
        paused=lambda: False,
        floor=0,
        heater_control=heat_control,
        window_sensor_entities=[],
        trv_entity=f"climate.trv_{name.lower().replace(' ', '_')}",
        temp_sensor_entity=f"sensor.{name.lower().replace(' ', '_')}_temp",
        effective_setpoint=lambda: 22.0,
        extra_state_attributes={},
    )


def _make_entry(zones):
    """Create a mock ConfigEntry with the given zone configs."""
    entry = MagicMock()
    entry.entry_id = ENTRY_ID
    entry.options = {CONF_ZONES: zones}
    entry.async_reload = AsyncMock()
    entry.async_on_unload = MagicMock()
    return entry


def _make_hass(entry, zone_objs):
    """Build a mock hass with data[DOMAIN] wired to controller zones."""
    ctrl = MagicMock()
    ctrl.zones = zone_objs
    ctrl.diagnostics = lambda: {}
    ctrl.outdoor_temp = lambda: 5.0
    ctrl.flow_setpoint = 50.0
    ctrl.total_demand = 0.0
    ctrl.active_zone_names = []
    ctrl.curve_coeff = 1.0
    ctrl.min_flow = 30.0
    ctrl.max_flow = 70.0

    hass = MagicMock()
    hass.data = {
        DOMAIN: {
            ENTRY_ID: {
                "controller": ctrl,
                "backend": MagicMock(),
                "backend_type": "hcs",
                "zones_cfg": list(zone_objs),
            },
            "firmware_manager": None,
        }
    }
    hass.config_entries.async_get_entry = MagicMock(return_value=entry)
    hass.config_entries.async_update_entry = MagicMock()
    hass.config_entries.async_reload = AsyncMock()
    hass.states.get = MagicMock(return_value=None)
    return hass, ctrl


# ── ws_rename_zone ──────────────────────────────────────────────────


class TestWsRenameZoneReload:
    """Verify ws_rename_zone calls async_reload before _collect_status."""

    def test_reload_called_before_response(self):
        """The entry must be reloaded so _collect_status sees fresh entities."""
        zones_cfg = [
            {CONF_ZONE_NAME: "Living", CONF_ZONE_HEAT_CONTROL: "smart"},
        ]
        zone_obj = _make_zone("Living", heat_control="smart")
        entry = _make_entry(zones_cfg)
        hass, ctrl = _make_hass(entry, [zone_obj])

        conn = MagicMock()
        msg = {"id": 1, "zone": "Living", "heat_control": "manual"}

        asyncio.run(ws_rename_zone(hass, conn, msg))

        hass.config_entries.async_reload.assert_awaited_once_with(ENTRY_ID)
        conn.send_result.assert_called_once()
        result = conn.send_result.call_args[0][1]
        assert result["ok"] is True

    def test_status_reflects_new_heat_control(self):
        """Even though entities are stale, async_reload + _collect_status
        must return the updated value because the zone object gets
        re-created with the new config after reload.
        """
        zones_cfg = [
            {CONF_ZONE_NAME: "Living", CONF_ZONE_HEAT_CONTROL: "smart"},
        ]
        zone_obj = _make_zone("Living", heat_control="smart")
        entry = _make_entry(zones_cfg)
        hass, ctrl = _make_hass(entry, [zone_obj])

        # Simulate what HA does: after async_reload, the zone is recreated
        # with the updated config.  Patch _collect_status to read the
        # controller's zones (which we swap during the reload mock).
        new_zone_obj = _make_zone("Living", heat_control="manual")

        async def simulate_reload(entry_id=None):
            ctrl.zones = [new_zone_obj]

        hass.config_entries.async_reload = AsyncMock(side_effect=simulate_reload)

        conn = MagicMock()
        msg = {"id": 2, "zone": "Living", "heat_control": "manual"}

        asyncio.run(ws_rename_zone(hass, conn, msg))

        hass.config_entries.async_reload.assert_awaited_once_with(ENTRY_ID)
        conn.send_result.assert_called_once()
        result = conn.send_result.call_args[0][1]
        status = result["status"]
        living = next(
            z for z in status["systems"][0]["zones"] if z["name"] == "Living"
        )
        assert living["heat_control"] == "manual"

    def test_rename_also_reflected(self):
        """Renaming + heat_control change: both should appear in response."""
        zones_cfg = [
            {CONF_ZONE_NAME: "Living", CONF_ZONE_HEAT_CONTROL: "smart"},
        ]
        zone_obj = _make_zone("Living", heat_control="smart")
        entry = _make_entry(zones_cfg)
        hass, ctrl = _make_hass(entry, [zone_obj])

        new_zone_obj = _make_zone("Lounge", heat_control="manual")

        async def simulate_reload(entry_id=None):
            ctrl.zones = [new_zone_obj]

        hass.config_entries.async_reload = AsyncMock(side_effect=simulate_reload)

        conn = MagicMock()
        msg = {"id": 3, "zone": "Living", "new_name": "Lounge", "heat_control": "manual"}

        asyncio.run(ws_rename_zone(hass, conn, msg))

        conn.send_result.assert_called_once()
        result = conn.send_result.call_args[0][1]
        status = result["status"]
        lounge = next(
            z for z in status["systems"][0]["zones"] if z["name"] == "Lounge"
        )
        assert lounge["heat_control"] == "manual"


# ── ws_add_zone ─────────────────────────────────────────────────────


class TestWsAddZoneReload:
    """Verify ws_add_zone calls async_reload before _collect_status."""

    def test_reload_called(self):
        entry = _make_entry([])
        hass, ctrl = _make_hass(entry, [])

        conn = MagicMock()
        msg = {
            "id": 10,
            "name": "Bedroom",
            "heat_control": "manual",
            "floor": 1,
            "trv_climates": [],
            "window_sensors": [],
        }

        asyncio.run(ws_add_zone(hass, conn, msg))

        hass.config_entries.async_reload.assert_awaited_once_with(ENTRY_ID)
        conn.send_result.assert_called_once()

    def test_new_zone_appears_in_status(self):
        entry = _make_entry([])
        hass, ctrl = _make_hass(entry, [])

        new_zone = _make_zone("Bedroom", heat_control="manual")

        async def simulate_reload(entry_id=None):
            ctrl.zones = [new_zone]

        hass.config_entries.async_reload = AsyncMock(side_effect=simulate_reload)

        conn = MagicMock()
        msg = {
            "id": 11,
            "name": "Bedroom",
            "heat_control": "manual",
            "floor": 0,
            "trv_climates": [],
            "window_sensors": [],
        }

        asyncio.run(ws_add_zone(hass, conn, msg))

        conn.send_result.assert_called_once()
        result = conn.send_result.call_args[0][1]
        status = result["status"]
        names = [z["name"] for z in status["systems"][0]["zones"]]
        assert "Bedroom" in names
        bedroom = next(z for z in status["systems"][0]["zones"] if z["name"] == "Bedroom")
        assert bedroom["heat_control"] == "manual"


# ── ws_remove_zone ──────────────────────────────────────────────────


class TestWsRemoveZoneReload:
    """Verify ws_remove_zone calls async_reload before _collect_status."""

    def test_reload_called(self):
        zones_cfg = [
            {CONF_ZONE_NAME: "Living", CONF_ZONE_HEAT_CONTROL: "smart"},
            {CONF_ZONE_NAME: "Bedroom", CONF_ZONE_HEAT_CONTROL: "manual"},
        ]
        zone_objs = [_make_zone("Living"), _make_zone("Bedroom", "manual")]
        entry = _make_entry(zones_cfg)
        hass, ctrl = _make_hass(entry, zone_objs)

        conn = MagicMock()
        msg = {"id": 20, "zone": "Bedroom"}

        asyncio.run(ws_remove_zone(hass, conn, msg))

        hass.config_entries.async_reload.assert_awaited_once_with(ENTRY_ID)
        conn.send_result.assert_called_once()

    def test_removed_zone_absent_from_status(self):
        zones_cfg = [
            {CONF_ZONE_NAME: "Living", CONF_ZONE_HEAT_CONTROL: "smart"},
            {CONF_ZONE_NAME: "Bedroom", CONF_ZONE_HEAT_CONTROL: "manual"},
        ]
        zone_objs = [_make_zone("Living"), _make_zone("Bedroom", "manual")]
        entry = _make_entry(zones_cfg)
        hass, ctrl = _make_hass(entry, zone_objs)

        async def simulate_reload(entry_id=None):
            ctrl.zones = [_make_zone("Living")]

        hass.config_entries.async_reload = AsyncMock(side_effect=simulate_reload)

        conn = MagicMock()
        msg = {"id": 21, "zone": "Bedroom"}

        asyncio.run(ws_remove_zone(hass, conn, msg))

        conn.send_result.assert_called_once()
        result = conn.send_result.call_args[0][1]
        status = result["status"]
        names = [z["name"] for z in status["systems"][0]["zones"]]
        assert "Bedroom" not in names
        assert "Living" in names
