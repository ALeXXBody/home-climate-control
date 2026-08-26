"""Radiator health flags: chronic deficit at saturated flow trips a warning."""

import pytest

from custom_components.home_climate_control.health import (
    CLEAR_AFTER_S,
    STRUGGLE_AFTER_S,
    STRUGGLE_AFTER_MAX_S,
    RoomHealthMonitor,
    load_patience_s,
)

TICK = 60.0


def feed(m, name, ts, demanding, deficit=1.2, flow_at_max=True, outdoor=None):
    return m.feed(
        name,
        ts,
        demanding=demanding,
        deficit_c=deficit if demanding else None,
        flow_at_max=flow_at_max,
        tick_s=TICK,
        outdoor=outdoor,
    )


def test_flag_raises_after_sustained_struggle():
    m = RoomHealthMonitor()
    t = 0.0
    flagged = False
    while t < STRUGGLE_AFTER_S:
        t += TICK
        flagged = feed(m, "Attic", t, True)
    assert flagged is True
    assert m.flag_for("Attic") == "struggling"


def test_no_flag_while_flow_not_saturated():
    m = RoomHealthMonitor()
    t = 0.0
    while t < STRUGGLE_AFTER_S * 2:
        t += TICK
        feed(m, "Hall", t, True, flow_at_max=False)
    assert m.flag_for("Hall") is None


def test_no_flag_when_deficit_small():
    m = RoomHealthMonitor()
    t = 0.0
    while t < STRUGGLE_AFTER_S * 2:
        t += TICK
        feed(m, "Snug", t, True, deficit=0.5)
    assert m.flag_for("Snug") is None


def test_transient_demand_does_not_trip():
    m = RoomHealthMonitor()
    t = 0.0
    # alternating demand/idle: streak keeps resetting
    for i in range(int(STRUGGLE_AFTER_S / TICK) * 3):
        t += TICK
        feed(m, "Study", t, demanding=(i % 2 == 0))
    assert m.flag_for("Study") is None


def test_flag_clears_on_recovery():
    m = RoomHealthMonitor()
    t = 0.0
    while t < STRUGGLE_AFTER_S:
        t += TICK
        feed(m, "Attic", t, True)
    assert m.flag_for("Attic")
    # deficit closes -> flag clears immediately
    assert feed(m, "Attic", t + TICK, True, deficit=0.1) is False
    assert m.flag_for("Attic") is None


def test_flag_clears_after_idle_period():
    m = RoomHealthMonitor()
    t = 0.0
    while t < STRUGGLE_AFTER_S:
        t += TICK
        feed(m, "Box Room", t, True)
    assert m.flag_for("Box Room")
    # stops demanding: flag survives briefly, then clears
    t += TICK
    assert feed(m, "Box Room", t, False) is True
    t += TICK
    while (t % CLEAR_AFTER_S) != 0 or t < CLEAR_AFTER_S:
        t += TICK
        feed(m, "Box Room", t, False)
    assert feed(m, "Box Room", t + TICK, False) is False


def test_load_patience_scales_with_outdoor():
    mild = load_patience_s(20.0)   # outdoor ≈ comfort → base
    cool = load_patience_s(5.0)
    cold = load_patience_s(-10.0)
    assert mild == pytest.approx(STRUGGLE_AFTER_S, abs=1.0)
    assert cool > mild
    assert cold > cool
    assert cold <= STRUGGLE_AFTER_MAX_S
    assert load_patience_s(None) == STRUGGLE_AFTER_S


def test_cold_day_needs_longer_streak():
    """Design-cold outdoor must not trip at the mild-weather threshold."""
    m = RoomHealthMonitor()
    t = 0.0
    while t < STRUGGLE_AFTER_S + 60:
        t += TICK
        feed(m, "Attic", t, True, outdoor=-10.0)
    # Still within cold-day patience → no flag yet
    assert m.flag_for("Attic") is None
    # Keep going until cold-day threshold
    need = load_patience_s(-10.0)
    while t < need:
        t += TICK
        feed(m, "Attic", t, True, outdoor=-10.0)
    assert m.flag_for("Attic") == "struggling"
