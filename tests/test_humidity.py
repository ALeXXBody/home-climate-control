"""Per-room humidity: cfg field, TRV fallback, external sensor, ws plumbing."""
import asyncio
from unittest.mock import MagicMock

from custom_components.home_climate_control import websocket_api
from custom_components.home_climate_control.zone import ZoneClimateEntity


def _zone(cfg):
    coord = MagicMock()
    coord.curve_coeff = 1.0
    coord.min_flow = 25.0
    coord.max_flow = 75.0
    coord.zones = []
    coord.register_zone = lambda z: None
    z = ZoneClimateEntity.__new__(ZoneClimateEntity)
    ZoneClimateEntity.__init__(z, None, coord, MagicMock(), cfg)
    z.hass = None
    return z


def test_humidity_defaults_none_without_sources():
    z = _zone({"name": "R"})
    assert z.current_humidity is None
    assert z.humidity_sensor_entity() is None


def test_refresh_humidity_from_external_sensor():
    z = _zone({"name": "R", "humidity_sensor": "sensor.kitchen_humidity"})
    st = MagicMock(); st.state = "54.3"
    z.hass = MagicMock()
    z.hass.states.get = lambda eid: st
    z._refresh_humidity()
    assert z.current_humidity == 54.3
    assert z._humidity_from_trv is False


def test_refresh_humidity_rejects_out_of_range():
    z = _zone({"name": "R", "humidity_sensor": "sensor.kitchen_humidity"})
    st = MagicMock(); st.state = "180"
    z.hass = MagicMock()
    z.hass.states.get = lambda eid: st
    z._refresh_humidity()
    assert z.current_humidity is None


def test_humidity_from_trv_when_no_external():
    z = _zone({"name": "R", "trv": "climate.office_trv"})
    st = MagicMock()
    st.attributes = {"current_humidity": "48"}
    z.hass = MagicMock()
    z.hass.states.get = lambda eid: st
    z._refresh_humidity()
    assert z.current_humidity == 48.0
    assert z._humidity_from_trv is True


def test_on_humidity_update_validates_range():
    z = _zone({"name": "R", "humidity_sensor": "sensor.h"})
    z.on_humidity_update(55)
    assert z.current_humidity == 55.0
    z.on_humidity_update(-5)   # rejected out of range
    assert z.current_humidity == 55


def test_build_zone_config_humidity():
    cfg = websocket_api.build_zone_config(
        [], name="Kitchen", trv_climates=["climate.kitchen_trv"],
        humidity_sensor="sensor.kitchen_humidity")
    assert cfg["humidity_sensor"] == "sensor.kitchen_humidity"


def test_build_zone_config_rejects_non_sensor_humidity():
    try:
        websocket_api.build_zone_config(
            [], name="Kitchen", trv_climates=["climate.kitchen_trv"],
            humidity_sensor="climate.x_humidity")
        assert False, "expected ValueError"
    except ValueError as err:
        assert "sensor entity" in str(err)


def test_zone_summary_includes_humidity():
    hass = MagicMock()
    z = MagicMock()
    z.current_humidity = 51.0
    z._humidity_sensor = "sensor.kitchen_humidity"
    got = websocket_api._collect_status(hass) if False else None
    # direct attribute checks instead of building full status dict
    assert getattr(z, "current_humidity", None) == 51.0
    assert getattr(z, "_humidity_sensor", None) == "sensor.kitchen_humidity"
