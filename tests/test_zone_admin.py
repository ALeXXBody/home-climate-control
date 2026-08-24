"""Room rename/remove: validation rules + learned-history migration."""

import pytest

from custom_components.home_climate_control.central import CentralController
from custom_components.home_climate_control.deadtime import DeadTimeEstimator
from custom_components.home_climate_control.health import RoomHealthMonitor
from custom_components.home_climate_control.insulation import InsulationScorer
from custom_components.home_climate_control.setback import SetbackLearner
from custom_components.home_climate_control.websocket_api import validate_zone_name


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
