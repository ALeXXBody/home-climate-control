"""Airflow-blockage watch: TRV satisfied while the room stays cold.

Diagnostic only — no control behavior changes from this flag.
"""

import pytest

from custom_components.home_climate_control.health import (
    BLOCK_ARM_DEFICIT_C,
    BLOCK_STREAK_S,
    RoomHealthMonitor,
)


TICK = 60.0


def _feed(m, zone, ts, *, demanding=True, deficit=1.2, trv_near=True):
    return m.feed(
        zone, ts,
        demanding=demanding, deficit_c=deficit, flow_at_max=True,
        tick_s=TICK, trv_near_target=trv_near,
    )


def test_blockage_arms_after_sustained_pattern():
    m = RoomHealthMonitor()
    ts = 1000.0
    # 44 min — not yet
    for i in range(44):
        assert _feed(m, "Office", ts + i * TICK) is False
    # 45th minute arms
    assert _feed(m, "Office", ts + 44 * TICK) is False
    assert m.block_for("Office") == "blocked_airflow"


def test_blockage_needs_heating_demand():
    """Room cold, TRV satisfied, but heating idle — not a blockage."""
    m = RoomHealthMonitor()
    ts = 1000.0
    for i in range(50):
        _feed(m, "Office", ts + i * TICK, demanding=False, deficit=2.0,
              trv_near=True)
    assert m.block_for("Office") is None


def test_blockage_needs_trv_satisfied():
    m = RoomHealthMonitor()
    ts = 1000.0
    for i in range(50):
        _feed(m, "Office", ts + i * TICK, trv_near=False)
    assert m.block_for("Office") is None


def test_blockage_disarms_when_demand_stops():
    m = RoomHealthMonitor()
    ts = 1000.0
    for i in range(46):
        _feed(m, "Office", ts + i * TICK)
    assert m.block_for("Office") == "blocked_airflow"
    _feed(m, "Office", ts + 46 * TICK, demanding=False)
    assert m.block_for("Office") is None


def test_blockage_disarms_when_room_catches_up():
    """Room warms back within 0.6 °C of target → cleared."""
    m = RoomHealthMonitor()
    ts = 1000.0
    for i in range(46):
        _feed(m, "Office", ts + i * TICK)
    assert m.block_for("Office") == "blocked_airflow"
    _feed(m, "Office", ts + 46 * TICK, deficit=0.3)
    assert m.block_for("Office") is None


def test_blockage_deficit_below_floor_does_not_arm():
    """A 0.5 °C gap is comfort overshoot territory, not blockage."""
    m = RoomHealthMonitor()
    ts = 1000.0
    for i in range(50):
        _feed(m, "Office", ts + i * TICK,
              demanding=True, deficit=0.5, trv_near=True)
    assert m.block_for("Office") is None


def test_as_dict_exposes_block():
    m = RoomHealthMonitor()
    ts = 1000.0
    for i in range(46):
        _feed(m, "Office", ts + i * TICK)
    d = m.as_dict()
    assert d["rooms"]["Office"]["block"] == "blocked_airflow"
    assert d["rooms"]["Office"]["flag"] is None   # separate from struggling
