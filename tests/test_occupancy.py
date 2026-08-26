"""Occupancy follower: phone trackers → away/home presets."""

from unittest.mock import MagicMock

from custom_components.home_climate_control.occupancy import (
    OccupancyFollower,
    aggregate_presence,
    is_home_state,
)


def test_is_home_state():
    assert is_home_state("home") is True
    assert is_home_state("on") is True
    assert is_home_state("not_home") is False
    assert is_home_state("away") is False
    assert is_home_state("unknown") is None
    assert is_home_state(None) is None


def test_aggregate_any_home_wins():
    assert aggregate_presence(["not_home", "home"]) == "home"
    assert aggregate_presence(["not_home", "away"]) == "away"
    assert aggregate_presence(["unknown", "unavailable"]) is None
    assert aggregate_presence([]) is None


def test_all_away_applies_away_preset():
    hass = MagicMock()

    def get_state(eid):
        st = MagicMock()
        st.state = "not_home"
        return st

    hass.states.get.side_effect = get_state
    f = OccupancyFollower(
        hass,
        entity_ids=["device_tracker.phone_a", "device_tracker.phone_b"],
        away_preset="away",
        home_preset="comfort",
        enabled=True,
    )

    class Z:
        heater_control = "smart"
        _preset = "comfort"
        _preset_source = "schedule"
        calls = 0

        def apply_schedule_preset(self, p):
            self.calls += 1
            self._preset = p
            return True

    z = Z()
    f.bind_zones([z])
    assert f.apply(force=True) == "away"
    assert z._preset == "away"
    assert z._preset_source == "occupancy"
    assert f.last_presence == "away"


def test_someone_home_uses_schedule_when_present():
    hass = MagicMock()
    st = MagicMock()
    st.state = "home"
    hass.states.get.return_value = st

    class Sched:
        enabled = True

        def current_preset(self):
            return "eco"  # night schedule while home

    f = OccupancyFollower(
        hass,
        entity_ids=["person.alex"],
        away_preset="away",
        home_preset="comfort",
        enabled=True,
        schedule=Sched(),
    )

    class Z:
        heater_control = "smart"
        _preset = "away"
        _preset_source = "occupancy"

        def apply_schedule_preset(self, p):
            self._preset = p
            return True

    z = Z()
    f.bind_zones([z])
    assert f.apply(force=True) == "eco"
    assert z._preset == "eco"


def test_disabled_is_noop():
    f = OccupancyFollower(
        MagicMock(),
        entity_ids=["device_tracker.x"],
        enabled=False,
    )
    assert f.apply(force=True) is None
    assert f.enabled is False


def test_user_sticky_until_presence_changes():
    hass = MagicMock()
    st = MagicMock()
    st.state = "not_home"
    hass.states.get.return_value = st
    f = OccupancyFollower(
        hass, entity_ids=["device_tracker.x"], enabled=True
    )

    class Z:
        heater_control = "smart"
        _preset = "boost"
        _preset_source = "user"
        calls = 0

        def apply_schedule_preset(self, p):
            self.calls += 1
            self._preset = p
            return True

    z = Z()
    f.bind_zones([z])
    f.last_presence = "away"
    f.apply(force=False)
    assert z.calls == 0
    st.state = "home"
    f.apply(force=False)
    assert z.calls == 1
