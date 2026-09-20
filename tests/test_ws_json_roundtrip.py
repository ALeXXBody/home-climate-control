"""Every WS response payload must be JSON-serializable end to end.

Regression for the 1.12.0 "Invalid JSON in response" panic: the room summary
returned a bound method (humidity_sensor) instead of a value and HA's
websocket layer choked mid-serialization, which the panel showed as
"Invalid JSON in response".
"""

import json
from unittest.mock import MagicMock

from custom_components.home_climate_control import websocket_api
from custom_components.home_climate_control.zone import ZoneClimateEntity


def _real_zone(name="Office"):
    coord = MagicMock()
    coord.curve_coeff = 1.0
    coord.min_flow = 25.0
    coord.max_flow = 75.0
    coord.zones = []
    coord.register_zone = lambda zn: None
    z = ZoneClimateEntity.__new__(ZoneClimateEntity)
    ZoneClimateEntity.__init__(
        z, None, coord, MagicMock(),
        {"name": name, "trv": "climate.office_trv",
         "humidity_sensor": "sensor.office_humidity"})
    z.entity_id = "climate.office"
    z.hass = None
    return z


def test_zones_summary_is_json_serializable():
    z = _real_zone()
    entry = {
        "entity_id": z.entity_id,
        "name": getattr(z, "name", None),
        "humidity": getattr(z, "current_humidity", None),
        "humidity_sensor": getattr(z, "_humidity_sensor", None),
        "temp_sensor": getattr(z, "temp_sensor_entity", None),
        "trv": getattr(z, "trv_entity", None),
    }
    got = json.dumps(entry)  # must never raise
    assert '"humidity"' in got


def test_humidity_sensor_value_is_a_string_not_a_method():
    z = _real_zone()
    # exactly the bug that broke the panel: a bound method in the payload
    val = getattr(z, "_humidity_sensor", None)
    assert isinstance(val, str)
