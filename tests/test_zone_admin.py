"""Room rename/remove: validation rules + learned-history migration."""

import pytest

from custom_components.home_climate_control.central import CentralController
from custom_components.home_climate_control.deadtime import DeadTimeEstimator
from custom_components.home_climate_control.health import RoomHealthMonitor
from custom_components.home_climate_control.insulation import InsulationScorer
from custom_components.home_climate_control.setback import SetbackLearner
from custom_components.home_climate_control.websocket_api import (
    build_zone_config,
    validate_zone_name,
    validate_zone_update,
)


# ------------------------------------------------------------------ naming

def test_validate_rejects_empty_and_duplicates():
    names = ["Living", "Bedroom"]
    assert validate_zone_name(names, "   ") is not None
    assert validate_zone_name(names, "living") is not None  # case-insensitive dup
    assert validate_zone_name(names, "Kitchen") is None


def test_validate_length_cap():
    assert validate_zone_name([], "x" * 41) is not None
    assert validate_zone_name([], "x" * 40) is None


def _controller_with_learners():
    ctrl = CentralController.__new__(CentralController)  # skip HA wiring
    ctrl.setbacks = SetbackLearner(None)
    ctrl.deadtime = DeadTimeEstimator(None)
    ctrl.insulation = InsulationScorer(None)
    ctrl.health = RoomHealthMonitor()
    from custom_components.home_climate_control.calibrate import RoomCalibrator

    ctrl.calibration = RoomCalibrator()

    # seed learned state under the old name
    st = ctrl.setbacks._room("Old Name")
    st.warm_ema = 3.3
    st.cycles = 2
    ctrl.deadtime.estimates["Old Name"] = 240.0
    dt = ctrl.deadtime._room("Old Name")
    dt.armed = False
    ins = ctrl.insulation._room("Old Name")
    ins.k_ema = 0.045
    ctrl.health.feed("Old Name", 0.0, demanding=True, deficit_c=1.5,
                     flow_at_max=True, tick_s=STRUGGLE_TICKS)
    return ctrl


STRUGGLE_TICKS = 60.0 * 100  # long enough to raise the flag


def test_rename_migrates_all_learned_state():
    ctrl = _controller_with_learners()
    ctrl.rename_zone_learning("Old Name", "New Name")
    assert "New Name" in ctrl.setbacks.rooms
    assert "Old Name" not in ctrl.setbacks.rooms
    assert ctrl.setbacks.rooms["New Name"].warm_ema == pytest.approx(3.3)
    assert ctrl.deadtime.estimates["New Name"] == pytest.approx(240.0)
    score = ctrl.insulation.score_for("New Name")
    assert score is not None and score[0] == "good"
    assert ctrl.health.flag_for("New Name") == "struggling"
    # nothing left under the old key anywhere
    assert "Old Name" not in ctrl.deadtime.rooms
    assert "Old Name" not in ctrl.insulation.rooms


def test_rename_does_not_clobber_existing_target():
    ctrl = _controller_with_learners()
    tgt = ctrl.setbacks._room("Existing")
    tgt.warm_ema = 9.9
    ctrl.rename_zone_learning("Old Name", "Existing")
    assert ctrl.setbacks.rooms["Existing"].warm_ema == pytest.approx(9.9)


def test_calibration_cancelled_on_rename():
    ctrl = _controller_with_learners()
    ctrl.calibration.start("Old Name", ts=100.0, temp=19.0)
    ctrl.rename_zone_learning("Old Name", "Renamed")
    assert ctrl.calibration.active() is False


# ------------------------------------------------------- house-model edits

def test_validate_update_requires_something():
    assert validate_zone_update(["A"]) is not None
    assert validate_zone_update(["A"], device_fields=True) is None


def test_validate_update_floor_bounds():
    assert validate_zone_update(["A"], floor=0) is None
    assert validate_zone_update(["A"], floor=30) is None
    assert validate_zone_update(["A"], floor=31) is not None
    assert validate_zone_update(["A"], floor=-1) is not None


def test_validate_update_control_values():
    assert validate_zone_update(["A"], heat_control="smart") is None
    assert validate_zone_update(["A"], heat_control="manual") is None
    assert validate_zone_update(["A"], heat_control="dumb") is not None


def test_validate_update_combines_rules():
    # valid rename + valid floor passes even with duplicate-check on others
    assert validate_zone_update(["B"], new_name="A", floor=2) is None
    # duplicate name still rejected inside a combined update
    err = validate_zone_update(["B", "C"], new_name="c", floor=1)
    assert err is not None and "already exists" in err


def _make_room(cfg):
    from unittest.mock import MagicMock
    from custom_components.home_climate_control.zone import ZoneClimateEntity

    hass = MagicMock()
    coord = MagicMock()
    coord.curve_coeff = 1.2
    coord.flow_setpoint = 45.0
    entry = MagicMock()
    entry.entry_id = "e1"
    room = ZoneClimateEntity(hass, coord, entry, {"name": "X", **cfg})
    room.async_write_ha_state = MagicMock()
    return room


def test_zone_defaults_and_custom_house_fields():
    room = _make_room({})
    assert room.floor == 0 and room.heater_control == "smart"
    room2 = _make_room({"floor": 2, "heat_control": "manual"})
    assert room2.floor == 2 and room2.heater_control == "manual"
    # garbage input falls back to safe defaults
    room3 = _make_room({"floor": "attic", "heat_control": "telepathy"})
    assert room3.floor == 0 and room3.heater_control == "smart"


# ------------------------------------------------------------ add new room

def test_build_zone_config_defaults():
    z = build_zone_config(["Living"], name="Kitchen", heat_control="manual")
    assert z["name"] == "Kitchen"
    assert z["heat_control"] == "manual"
    assert z["floor"] == 0
    assert z["setpoint"] == 20.0


def test_build_zone_config_smart_requires_trv():
    with pytest.raises(ValueError, match="TRV"):
        build_zone_config([], name="Study", heat_control="smart")
    z = build_zone_config([], name="Study", heat_control="smart",
                          trv_climates=["climate.trv_study"])
    assert z["trv_climates"] == ["climate.trv_study"]


def test_build_zone_config_manual_needs_no_trv():
    z = build_zone_config([], name="Hall", heat_control="manual")
    assert z["trv_climates"] == []


def test_build_zone_config_rejects_bad_entities():
    with pytest.raises(ValueError, match="climate"):
        build_zone_config([], name="A", heat_control="smart",
                          trv_climates=["switch.foo"])
    with pytest.raises(ValueError, match="sensor"):
        build_zone_config([], name="A", heat_control="manual",
                          temp_sensor="binary_sensor.x")


def test_build_zone_config_duplicate_and_empty_names():
    with pytest.raises(ValueError, match="already exists"):
        build_zone_config(["A", "B"], name="b")
    with pytest.raises(ValueError):
        build_zone_config([], name="   ")


def test_build_zone_config_floor_clamped():
    kw = {"heat_control": "manual"}
    assert build_zone_config([], name="A", floor=99, **kw)["floor"] == 30
    assert build_zone_config([], name="A", floor=-3, **kw)["floor"] == 0
