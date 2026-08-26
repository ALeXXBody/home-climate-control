"""Schedule → preset follower."""

from unittest.mock import MagicMock

import pytest

from custom_components.home_climate_control.schedule import (
    ScheduleFollower,
    resolve_preset,
)


def test_resolve_schedule_on_off():
    assert (
        resolve_preset("on", entity_id="schedule.heat", on_preset="comfort", off_preset="eco")
        == "comfort"
    )
    assert (
        resolve_preset("off", entity_id="schedule.heat", on_preset="comfort", off_preset="away")
        == "away"
    )


def test_resolve_direct_presets_and_aliases():
    assert resolve_preset("eco") == "eco"
    assert resolve_preset("AWAY") == "away"
    assert resolve_preset("home") == "comfort"
    assert resolve_preset("not_home") == "away"
    assert resolve_preset("night") == "eco"
    assert resolve_preset("boost") == "boost"
    assert resolve_preset("unknown") is None
    assert resolve_preset(None) is None


def test_follower_applies_to_smart_zones_only():
    hass = MagicMock()
    st = MagicMock()
    st.state = "off"
    hass.states.get.return_value = st

    f = ScheduleFollower(
        hass, entity_id="schedule.heat", on_preset="comfort", off_preset="eco"
    )

    class Z:
        def __init__(self, name, control="smart"):
            self.name = name
            self.heater_control = control
            self._preset = "none"
            self._preset_source = "schedule"
            self.calls = 0

        def apply_schedule_preset(self, p):
            self.calls += 1
            self._preset = p
            self._preset_source = "schedule"
            return True

    smart = Z("Living")
    manual = Z("Hall", control="manual")
    f.bind_zones([smart, manual])
    assert f.apply(force=True) == "eco"
    assert smart._preset == "eco"
    assert smart.calls == 1
    assert manual.calls == 0


def test_user_override_sticky_until_schedule_changes():
    hass = MagicMock()
    st = MagicMock()
    st.state = "off"
    hass.states.get.return_value = st
    f = ScheduleFollower(hass, entity_id="schedule.heat")

    class Z:
        heater_control = "smart"
        _preset = "eco"
        _preset_source = "user"  # user overrode
        calls = 0

        def apply_schedule_preset(self, p):
            self.calls += 1
            self._preset = p
            self._preset_source = "schedule"
            return True

    z = Z()
    f.bind_zones([z])
    f.last_state = "off"  # already saw this window
    f.apply(force=False)
    assert z.calls == 0  # sticky
    # Schedule advances to on → override ends
    st.state = "on"
    f.apply(force=False)
    assert z.calls == 1
    assert z._preset == "comfort"


def test_as_dict_shape():
    f = ScheduleFollower(None, entity_id="schedule.x", enabled=True)
    f.last_preset = "eco"
    f.last_state = "off"
    d = f.as_dict()
    assert d["entity_id"] == "schedule.x"
    assert d["last_preset"] == "eco"
