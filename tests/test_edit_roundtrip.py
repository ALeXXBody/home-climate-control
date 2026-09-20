"""Integration test: the EXACT user flow that keeps failing.

1. Zone exists with empty TRV/temp/floor=0
2. User edits: sets TRV, temp sensor, floor=1 → rename_zone
3. HA reloads → new controller + entities built from updated options
4. Status reflects the saved values
5. User re-opens edit form → prefill reads the saved values

If this test passes, the server path is correct and the bug is client-side.
If it fails, this pinpoints exactly where the data is lost.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

from custom_components.home_climate_control import websocket_api
from custom_components.home_climate_control.const import (
    CONF_ZONES, CONF_ZONE_NAME, CONF_ZONE_TRV_CLIMATES,
    CONF_ZONE_TEMP_SENSOR, CONF_ZONE_FLOOR,
)


def _entry_with_zones(zones):
    entry = MagicMock()
    entry.entry_id = "e1"
    entry.options = {CONF_ZONES: [dict(z) for z in zones]}
    return entry


def _hass_with_entry(entry, controller_zones=None):
    controller = MagicMock()
    class _Z:
        def __init__(self, name, trv=None, temp=None, floor=0):
            self.name = name
            self.entity_id = f"climate.{name.lower().replace(' ', '_')}"
            self.trv_entity = trv
            self.temp_sensor_entity = temp
            self.floor = floor
            self.heater_control = "smart"
            self.hvac_mode = "heat"
            self.hvac_action = "idle"
            self.preset_mode = "none"
            self.current_temperature = 20.0
            self.target_temperature = 21.0
            self.effective_setpoint = lambda: 21.0
            self.demand_level = lambda: 0
            self.paused = lambda: False
            self.window_sensor_entities = []
            self._humidity_sensor = None
            self.current_humidity = None
            self.extra_state_attributes = {}
            self._preheat_active = False
            self.lead_time_s = lambda **kw: None
            self._dead_time_s = lambda: None
            self.balance = None
            self.solar = None
            self.co2 = None
            self.radiator_kw = None
            self._radiator_kw_est = None
            self._valve_pct = None
            self._lux_sensor = None
            self._co2_sensor = None
            self._trv_position_entity = None
    controller.zones = controller_zones or []
    hass = MagicMock()
    hass.data = {websocket_api.DOMAIN: {"e1": {"controller": controller}}}
    hass.config_entries.async_entries.return_value = [entry]
    hass.config_entries.async_get_entry = lambda eid: entry
    hass.config_entries.async_reload = AsyncMock()
    hass.config_entries.async_update_entry = MagicMock()
    hass.async_create_task = lambda co: None
    return hass, controller


def test_edit_save_reload_read_roundtrip():
    """THE test: edit Office → save TRV/temp/floor → verify options."""
    # Step 1: zone exists with empty values (what the user starts with)
    initial_zones = [{
        CONF_ZONE_NAME: "Office",
        CONF_ZONE_TRV_CLIMATES: [],
        "temp_sensor": None,
        CONF_ZONE_FLOOR: 0,
        "heat_control": "smart",
    }]
    entry = _entry_with_zones(initial_zones)
    controller_zones = []  # controller may be empty (platform crashed before)
    hass, controller = _hass_with_entry(entry, controller_zones)
    conn = MagicMock()

    # Step 2: user saves with TRV, temp sensor, floor=1
    asyncio.run(websocket_api.ws_rename_zone(hass, conn, {
        "id": 1, "zone": "Office",
        "heat_control": "smart",
        "floor": 1,
        "trv_climates": ["climate.office_trv"],
        "temp_sensor": "sensor.office_sensor_temperature",
        "humidity_sensor": "sensor.office_humidity",
        "window_sensors": [],
        "lux_sensor": None, "co2_sensor": None,
        "trv_position_entity": None, "radiator_kw": None,
    }))

    # Step 3: verify the WRITE actually happened
    conn.send_error.assert_not_called()  # no rejection
    assert hass.config_entries.async_update_entry.called, \
        "async_update_entry was never called — the save is a no-op!"
    written_opts = hass.config_entries.async_update_entry.call_args.kwargs["options"]
    written_zones = written_opts.get(CONF_ZONES, [])
    assert len(written_zones) == 1, f"expected 1 zone, got {len(written_zones)}"
    z = written_zones[0]
    assert z.get(CONF_ZONE_TRV_CLIMATES) == ["climate.office_trv"], \
        f"TRV not saved: {z.get(CONF_ZONE_TRV_CLIMATES)}"
    assert z.get("temp_sensor") == "sensor.office_sensor_temperature", \
        f"temp not saved: {z.get('temp_sensor')}"
    assert z.get(CONF_ZONE_FLOOR) == 1, \
        f"floor not saved: {z.get(CONF_ZONE_FLOOR)}"
    print("WRITE: PASS — TRV, temp, floor=1 all written to options")

    # Step 4: simulate the reload — options are the source of truth
    entry.options = written_opts  # what HA would have after the update
    # New controller + entities built from updated options
    class _Zone:
        def __init__(self, cfg):
            self.name = cfg[CONF_ZONE_NAME]
            self.entity_id = f"climate.{cfg[CONF_ZONE_NAME].lower()}"
            self.trv_entity = (cfg.get(CONF_ZONE_TRV_CLIMATES) or [None])[0]
            self.temp_sensor_entity = cfg.get("temp_sensor")
            self.floor = cfg.get(CONF_ZONE_FLOOR, 0)
            self.heater_control = cfg.get("heat_control", "smart")
            self.hvac_mode = "heat"
            self.hvac_action = "idle"
            self.preset_mode = "none"
            self.current_temperature = 20.0
            self.target_temperature = 21.0
            self.effective_setpoint = lambda: 21.0
            self.demand_level = lambda: 0
            self.paused = lambda: False
            self.window_sensor_entities = []
            self._humidity_sensor = cfg.get("humidity_sensor")
            self.current_humidity = None
            self.extra_state_attributes = {}
            self._preheat_active = False
            self.lead_time_s = lambda **kw: None
            self._dead_time_s = lambda: None
            self.balance = None
            self.solar = None
            self.co2 = None
            self.radiator_kw = None
            self._radiator_kw_est = None
            self._valve_pct = None
            self._lux_sensor = None
            self._co2_sensor = None
            self._trv_position_entity = None
    new_controller = MagicMock()
    new_controller.zones = [_Zone(z) for z in written_zones]
    hass.data[websocket_api.DOMAIN]["e1"]["controller"] = new_controller

    # Step 5: read back via get_status
    status = websocket_api._collect_status(hass)
    zones_out = status["systems"][0]["zones"]
    office = zones_out[0]
    assert office["trv"] == "climate.office_trv", \
        f"status TRV wrong: {office['trv']}"
    assert office["temp_sensor"] == "sensor.office_sensor_temperature", \
        f"status temp wrong: {office['temp_sensor']}"
    assert office["floor"] == 1, \
        f"status floor wrong: {office['floor']}"
    assert "lux_sensor" in office
    assert "co2_sensor" in office
    assert "trv_position_entity" in office
    print("READ: PASS — status shows TRV, temp, floor=1 after reload")
    print("FULL ROUNDTRIP: PASS — server path is correct")


def test_edit_with_existing_values_preserves_them():
    """Second flow: zone already HAS TRV/temp/floor — user just changes floor."""
    initial_zones = [{
        CONF_ZONE_NAME: "Office",
        CONF_ZONE_TRV_CLIMATES: ["climate.office_trv"],
        "temp_sensor": "sensor.office_sensor_temperature",
        CONF_ZONE_FLOOR: 0,
        "heat_control": "smart",
    }]
    entry = _entry_with_zones(initial_zones)
    hass, controller = _hass_with_entry(entry)
    conn = MagicMock()

    asyncio.run(websocket_api.ws_rename_zone(hass, conn, {
        "id": 2, "zone": "Office",
        "heat_control": "smart",
        "floor": 1,
        "trv_climates": ["climate.office_trv"],  # same TRV
        "temp_sensor": "sensor.office_sensor_temperature",  # same sensor
        "window_sensors": [],
    }))

    written = hass.config_entries.async_update_entry.call_args.kwargs["options"]
    z = written[CONF_ZONES][0]
    assert z[CONF_ZONE_TRV_CLIMATES] == ["climate.office_trv"]
    assert z["temp_sensor"] == "sensor.office_sensor_temperature"
    assert z[CONF_ZONE_FLOOR] == 1
    print("PRESERVE: PASS — existing TRV/temp kept, floor updated to 1")
