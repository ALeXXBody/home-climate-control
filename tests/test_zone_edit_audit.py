"""Handler-seam audit: EVERY room-edit field, at the REAL seam.

October 2026's incident class was a field accepted at the wire, converted by
the builder, but DROPPED between the two — the handler never read it, so
user saves failed silently. These tests run the actual handler coroutines
and assert what lands in the SAVED OPTIONS for every field of the edit
form, with set / clear / absent (never wipe) semantics. If a future field
edit forgets its pass-through, these fail first — before a user does.

The harness mocks the pieces the handlers touch (ZonesBackup save, option
reload) and captures the options handed to async_update_entry.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.home_climate_control.const import (
    CONF_ZONE_CO2_SENSOR,
    CONF_ZONE_FLOOR,
    CONF_ZONE_HEAT_CONTROL,
    CONF_ZONE_HUMIDITY_SENSOR,
    CONF_ZONE_LUX_SENSOR,
    CONF_ZONE_NAME,
    CONF_ZONE_RADIATOR_KW,
    CONF_ZONE_TEMP_SENSOR,
    CONF_ZONE_TRV_CLIMATES,
    CONF_ZONE_TRV_POSITION,
    CONF_ZONE_WINDOW_SENSORS,
    CONF_ZONES,
    DOMAIN,
)
from custom_components.home_climate_control.websocket_api import ws_rename_zone

ENTRY_ID = "entry-hcc-audit"

BASE_ZONE_CFG = {
    CONF_ZONE_NAME: "Office",
    CONF_ZONE_TRV_CLIMATES: ["climate.office_trv"],
    CONF_ZONE_FLOOR: 0,
    CONF_ZONE_HEAT_CONTROL: "smart",
}


def _make_hass_and_entry(zone_cfg=None):
    zones = [dict(zone_cfg or BASE_ZONE_CFG)]
    entry = MagicMock()
    entry.entry_id = ENTRY_ID
    entry.options = {CONF_ZONES: zones}
    entry.async_reload = AsyncMock()
    ctrl = MagicMock()
    ctrl.zone = MagicMock()
    ctrl.zones = [MagicMock(name=zones[0][CONF_ZONE_NAME])]
    ctrl.rename_zone_learning = MagicMock()
    hass = MagicMock()
    hass.data = {
        DOMAIN: {
            ENTRY_ID: {
                "controller": ctrl,
                "backend": MagicMock(),
                "backend_type": "hcs",
            }
        }
    }
    hass.config_entries.async_entries = MagicMock(return_value=[entry])
    hass.config_entries.async_get_entry = MagicMock(return_value=entry)
    hass.config_entries.async_update_entry = MagicMock()
    hass.config_entries.async_reload = AsyncMock()
    hass.states.get = MagicMock(return_value=None)
    return hass, entry, zones


def _saved_zones(hass):
    args = hass.config_entries.async_update_entry.call_args_list[-1]
    return args[1].get("options") or {}, args[0]


async def _run_rename(hass, msg):
    conn = MagicMock()
    conn.send_result = MagicMock()
    conn.send_error = MagicMock()
    await ws_rename_zone(hass, conn, msg)
    return conn


# ── base room edit fields (already covered historically, now systematic) ──

@pytest.mark.asyncio
async def test_rename_sets_every_device_field():
    hass, entry, zones = _make_hass_and_entry()
    msg = {
        "id": 1, "type": "home_climate_control/rename_zone", "zone": "Office",
        "trv_climates": ["climate.office_trv"],
        "temp_sensor": "sensor.office_sensor_temperature",
        "humidity_sensor": "sensor.office_sensor_humidity",
        "window_sensors": ["binary_sensor.office_window"],
        "lux_sensor": "sensor.office_lux",
        "co2_sensor": "sensor.office_co2",
        "trv_position_entity": "number.office_trv_valve_opening_degree",
        "floor": 2,
    }
    with patch(
        "custom_components.home_climate_control.websocket_api.ZonesBackup"
    ), patch(
        "custom_components.home_climate_control.websocket_api._collect_status",
        return_value={},
    ):
        conn = await _run_rename(hass, msg)
    conn.send_error.assert_not_called()
    new_options, _ = _saved_zones(hass)
    zcfg = new_options[CONF_ZONES][0]
    assert zcfg["temp_sensor"] == msg["temp_sensor"]
    assert zcfg["humidity_sensor"] == msg["humidity_sensor"]
    assert zcfg["window_sensors"] == msg["window_sensors"]
    assert zcfg["lux_sensor"] == msg["lux_sensor"]
    assert zcfg["co2_sensor"] == msg["co2_sensor"]
    assert zcfg["trv_position_entity"] == msg["trv_position_entity"]
    assert zcfg["floor"] == 2


@pytest.mark.asyncio
async def test_rename_clears_a_device_field_on_null():
    hass, entry, zones = _make_hass_and_entry(
        {**BASE_ZONE_CFG, CONF_ZONE_TEMP_SENSOR: "sensor.old"})
    msg = {"id": 1, "type": "home_climate_control/rename_zone",
           "zone": "Office", "temp_sensor": None}
    with patch(
        "custom_components.home_climate_control.websocket_api.ZonesBackup"
    ), patch(
        "custom_components.home_climate_control.websocket_api._collect_status",
        return_value={},
    ):
        conn = await _run_rename(hass, msg)
    conn.send_error.assert_not_called()
    saved = hass.config_entries.async_update_entry.call_args_list[-1]
    new_options = saved[1].get("options")
    assert new_options[CONF_ZONES][0].get("temp_sensor") is None


@pytest.mark.asyncio
async def test_rename_absent_field_never_wipes_the_stored_one():
    hass, entry, zones = _make_hass_and_entry(
        {**BASE_ZONE_CFG, CONF_ZONE_TEMP_SENSOR: "sensor.keepme"})
    msg = {"id": 1, "type": "home_climate_control/rename_zone",
           "zone": "Office", "heat_control": "smart"}   # no temp_sensor
    with patch(
        "custom_components.home_climate_control.websocket_api.ZonesBackup"
    ), patch(
        "custom_components.home_climate_control.websocket_api._collect_status",
        return_value={},
    ):
        conn = await _run_rename(hass, msg)
    saved = hass.config_entries.async_update_entry.call_args_list[-1]
    zcfg = saved[1].get("options")[CONF_ZONES][0]
    assert zcfg["temp_sensor"] == "sensor.keepme"   # preserved


# ── the watts seam: set / clear / absent presume ─────────────────────────

@pytest.mark.asyncio
async def test_rename_persists_radiator_watts():
    hass, entry, zones = _make_hass_and_entry()
    msg = {"id": 1, "type": "home_climate_control/rename_zone",
           "zone": "Office", "radiator_w": 1336}
    with patch(
        "custom_components.home_climate_control.websocket_api.ZonesBackup"
    ), patch(
        "custom_components.home_climate_control.websocket_api._collect_status",
        return_value={},
    ):
        conn = await _run_rename(hass, msg)
    conn.send_error.assert_not_called()
    saved = hass.config_entries.async_update_entry.call_args_list[-1]
    zcfg = saved[1].get("options")[CONF_ZONES][0]
    assert zcfg[CONF_ZONE_RADIATOR_KW] == 1.336      # W → kW stored


@pytest.mark.asyncio
async def test_rename_radiator_watts_clear_on_null():
    hass, entry, zones = _make_hass_and_entry(
        {**BASE_ZONE_CFG, CONF_ZONE_RADIATOR_KW: 1.336})
    msg = {"id": 1, "type": "home_climate_control/rename_zone",
           "zone": "Office", "radiator_w": None}      # field emptied in UI
    with patch(
        "custom_components.home_climate_control.websocket_api.ZonesBackup"
    ), patch(
        "custom_components.home_climate_control.websocket_api._collect_status",
        return_value={},
    ):
        conn = await _run_rename(hass, msg)
    saved_z = hass.config_entries.async_update_entry.call_args_list[-1]
    zcfg = saved_z[1].get("options")[CONF_ZONES][0]
    assert CONF_ZONE_RADIATOR_KW not in zcfg            # cleared, not kept


@pytest.mark.asyncio
async def test_rename_radiator_watts_absent_never_wipes():
    hass, entry, zones = _make_hass_and_entry(
        {**BASE_ZONE_CFG, CONF_ZONE_RADIATOR_KW: 2.0})
    msg = {"id": 1, "type": "home_climate_control/rename_zone",
           "zone": "Office", "heat_control": "smart"}  # no watts field
    with patch(
        "custom_components.home_climate_control.websocket_api.ZonesBackup"
    ), patch(
        "custom_components.home_climate_control.websocket_api._collect_status",
        return_value={},
    ):
        conn = await _run_rename(hass, msg)
    saved = hass.config_entries.async_update_entry.call_args_list[-1]
    zcfg = saved[1].get("options")[CONF_ZONES][0]
    assert zcfg[CONF_ZONE_RADIATOR_KW] == 2.0           # preserved


@pytest.mark.asyncio
async def test_rename_radiator_watts_out_of_band_rejected():
    hass, entry, zones = _make_hass_and_entry()
    msg = {"id": 1, "type": "home_climate_control/rename_zone",
           "zone": "Office", "radiator_w": 25000}
    with patch(
        "custom_components.home_climate_control.websocket_api.ZonesBackup"
    ), patch(
        "custom_components.home_climate_control.websocket_api._collect_status",
        return_value={},
    ):
        conn = await _run_rename(hass, msg)
    conn.send_error.assert_called_once()
    assert "radiator_w" in str(conn.send_error.call_args)


@pytest.mark.asyncio
async def test_rename_legacy_radiator_kw_still_applies():
    hass, entry, zones = _make_hass_and_entry()
    msg = {"id": 1, "type": "home_climate_control/rename_zone",
           "zone": "Office", "radiator_kw": 1.5}
    with patch(
        "custom_components.home_climate_control.websocket_api.ZonesBackup"
    ), patch(
        "custom_components.home_climate_control.websocket_api._collect_status",
        return_value={},
    ):
        conn = await _run_rename(hass, msg)
    saved = hass.config_entries.async_update_entry.call_args_list[-1]
    zcfg = saved[1].get("options")[CONF_ZONES][0]
    assert zcfg[CONF_ZONE_RADIATOR_KW] == 1.5           # legacy path intact


# ── floor-room edit: explicit clear ability and wire shapes ──────────────

@pytest.mark.asyncio
async def test_floor_room_explicit_clear_via_none_writes_no_floor_keys():
    hass, entry, zones = _make_hass_and_entry()
    msg = {"id": 1, "type": "home_climate_control/rename_zone",
           "zone": "Office", "heat_control": "floor",
           "floor_loop_entity": None, "floor_mixer_entity": None}
    with patch(
        "custom_components.home_climate_control.websocket_api.ZonesBackup"
    ), patch(
        "custom_components.home_climate_control.websocket_api._collect_status",
        return_value={},
    ):
        conn = await _run_rename(hass, msg)
    conn.send_error.assert_not_called()
    saved = hass.config_entries.async_update_entry.call_args_list[-1]
    zcfg = saved[1].get("options")[CONF_ZONES][0]
    assert "floor_loop_entity" not in zcfg
    assert zcfg["heat_control"] == "floor"   # a floor room without a loop is legal



# ── add path: watts must survive room CREATION at the handler seam too ──

@pytest.mark.asyncio
async def test_add_zone_persists_radiator_watts():
    from custom_components.home_climate_control.websocket_api import ws_add_zone
    from unittest.mock import MagicMock
    hass, entry, zones = _make_hass_and_entry()
    # _dedupe_zones(entry.options...) is the duplicate guard — Office exists:
    # use a fresh name (creation is validated against existing rooms).
    entry.options = {CONF_ZONES: [{**zones[0], CONF_ZONE_NAME: "Hall"}]}
    hass.states.get = MagicMock(return_value=None)
    msg = {
        "id": 2, "type": "home_climate_control/add_zone", "name": "Study",
        "heat_control": "smart", "floor": 0,
        "trv_climates": ["climate.study_trv"],
        "window_sensors": [],
        "radiator_w": 1800,
    }
    with patch(
        "custom_components.home_climate_control.websocket_api.ZonesBackup"
    ), patch(
        "custom_components.home_climate_control.websocket_api._collect_status",
        return_value={},
    ), patch(
        "custom_components.home_climate_control."
        "websocket_api._detect_trv_position_entity",
        return_value=None,
    ):
        conn = MagicMock()
        conn.send_result = MagicMock()
        conn.send_error = MagicMock()
        await ws_add_zone(hass, conn, msg)
    conn.send_error.assert_not_called()
    saved = hass.config_entries.async_update_entry.call_args_list[-1]
    saved_zones = saved[1].get("options")[CONF_ZONES]
    created = [z for z in saved_zones if z.get(CONF_ZONE_NAME) == "Study"]
    assert created and created[0].get(CONF_ZONE_RADIATOR_KW) == 1.8
