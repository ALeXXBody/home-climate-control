

def test_rename_zone_without_device_fields_keeps_them():
    """If the panel omits a device field (stale/half-rendered form), the
    stored config must NOT be wiped — matches the 1.12.2 client contract."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    from custom_components.home_climate_control import websocket_api
    from custom_components.home_climate_control.const import (
        CONF_ZONES,
        CONF_ZONE_NAME,
        CONF_ZONE_TEMP_SENSOR,
        CONF_ZONE_TRV_CLIMATES,
    )

    rooms = [{
        CONF_ZONE_NAME: "Office",
        CONF_ZONE_TRV_CLIMATES: ["climate.office_trv"],
        CONF_ZONE_TEMP_SENSOR: "sensor.office_sensor_temperature",
        "humidity_sensor": "sensor.office_humidity",
        "window_sensors": [],
    }]
    entry = MagicMock()
    entry.entry_id = "e1"
    entry.options = {CONF_ZONES: [dict(r) for r in rooms]}
    controller = MagicMock()
    class _Z:
        name = "Office"
    controller.zones = [_Z()]
    hass = MagicMock()
    hass.data = {websocket_api.DOMAIN: {"e1": {"controller": controller}}}
    hass.config_entries.async_entries.return_value = [entry]
    hass.config_entries.async_get_entry = lambda eid: entry
    hass.config_entries.async_reload = AsyncMock()
    conn = MagicMock()

    # Panel's "control" toggle path: heat_control only — must not touch devices
    asyncio.run(websocket_api.ws_rename_zone(
        hass, conn, {"id": 1, "zone": "Office", "heat_control": "manual"}))
    opts = hass.config_entries.async_update_entry.call_args.kwargs["options"]
    z = (opts.get(CONF_ZONES) or [{}])[0]
    assert z[CONF_ZONE_TRV_CLIMATES] == ["climate.office_trv"]
    assert z[CONF_ZONE_TEMP_SENSOR] == "sensor.office_sensor_temperature"
    assert z.get("humidity_sensor") == "sensor.office_humidity"
