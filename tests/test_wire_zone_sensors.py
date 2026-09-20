"""wire_zone_sensors must not write HA state before entities attach."""

from unittest.mock import MagicMock, patch

from custom_components.home_climate_control import wire_zone_sensors
from custom_components.home_climate_control.zone import ZoneClimateEntity


def _zone(name="Office", temp="sensor.office_temp", trv="climate.office_trv"):
    coord = MagicMock()
    coord.curve_coeff = 1.0
    coord.min_flow = 25.0
    coord.max_flow = 75.0
    coord.zones = []
    coord.register_zone = lambda z: None
    z = ZoneClimateEntity.__new__(ZoneClimateEntity)
    ZoneClimateEntity.__init__(
        z, MagicMock(), coord, MagicMock(),
        {"name": name, "trv": trv, "temp_sensor": temp},
    )
    z.hass = MagicMock()
    z.entity_id = None
    z.platform = None
    return z


def test_wire_zone_sensors_does_not_raise_before_attach():
    hass = MagicMock()
    st = MagicMock()
    st.state = "21.4"
    hass.states.get.return_value = st
    z = _zone()
    with patch(
        "homeassistant.helpers.event.async_track_state_change_event",
        return_value=lambda: None,
    ):
        wire_zone_sensors(hass, MagicMock(), [z])
