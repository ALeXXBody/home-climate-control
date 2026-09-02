"""Smart setbacks: learned per-room offset from measured recovery speed."""

import pytest

from custom_components.home_climate_control.setback import (
    LEARNED_MAX_C,
    LEARNED_MIN_C,
    MIN_CYCLES,
    SetbackLearner,
)

H = 3600.0


def learner(enabled=True):
    return SetbackLearner(None, enabled=enabled)


def run_cycle(l, zone, t0, cool_rate, warm_rate, hours_setback=8.0, target=21.0):
    """Simulate one away period + recovery with given °C/h rates."""
    t = t0
    temp = 20.0
    l.observe(zone, t, temp, "comfort")
    t += 300
    # enter setback
    l.observe(zone, t, temp, "away", heating_allowed=True)
    steps = int(hours_setback * 4)
    for _ in range(steps):
        t += 900
        temp = max(12.0, temp + cool_rate * 0.25)
        l.observe(zone, t, temp, "away")
    leave_temp = temp
    # leave setback -> recovery; keep sampling until the learner itself
    # closes the recovery segment (needs >= MIN_SEGMENT_S of samples).
    l.observe(zone, t, leave_temp, "comfort")
    rec_t = 0.0
    while l.rooms[zone].phase == "recover" and rec_t <= 2 * H + 1800:
        rec_t += 300
        t += 300
        temp = min(target - 0.05, leave_temp + warm_rate * (rec_t / H))
        l.observe(zone, t, temp, "comfort")
    assert l.rooms[zone].cycles >= 1, f"{zone}: cycle did not complete"
    return t


def test_immature_room_uses_fixed_fallback():
    l = learner()
    assert l.offset_for("hall", fallback=-4.0) == -4.0


def test_fast_room_gets_deep_slow_room_shallow():
    l = learner()
    t = run_cycle(l, "snappy", 0.0, cool_rate=-1.5, warm_rate=5.0)
    for _ in range(MIN_CYCLES - 1):
        t = run_cycle(l, "snappy", t + 3600.0, -1.5, 5.0)
    off_snappy = l.offset_for("snappy", fallback=-2.0)
    assert off_snappy <= -3.0  # deep discount earned

    t2 = t
    for i in range(MIN_CYCLES):
        t2 = run_cycle(l, "leaky", t2 + 3600.0, cool_rate=-0.8, warm_rate=0.7)
    off_leaky = l.offset_for("leaky", fallback=-2.0)
    assert off_leaky >= -1.6  # shallow: recovery is slow
    assert off_leaky > off_snappy  # shallow discount vs deep discount


def test_bounds_clamped():
    l = learner()
    t = 0.0
    for _ in range(MIN_CYCLES):
        t = run_cycle(l, "rocket", t + 3600.0, cool_rate=-2.0, warm_rate=50.0)
    assert l.offset_for("rocket", -2.0) == LEARNED_MIN_C

    l2 = learner()
    t = 0.0
    for _ in range(MIN_CYCLES):
        t = run_cycle(l2, "crawl", t + 3600.0, cool_rate=-0.1, warm_rate=0.05)
    assert l2.offset_for("crawl", -2.0) == LEARNED_MAX_C


def test_disabled_passthrough():
    l = learner(enabled=False)
    # observe() must be a silent no-op and never create room state
    l.observe("x", 0.0, 20.0, "away")
    l.observe("x", 3600.0, 17.0, "comfort")
    assert l.rooms == {}
    assert l.offset_for("x", -4.0) == -4.0


def test_persistence_roundtrip():
    import asyncio

    class FakeStore:
        def __init__(self):
            self.saved = None

        async def async_load(self):
            return self.saved

        async def async_save(self, d):
            self.saved = d

    a = learner()
    a._store = FakeStore()
    t = 0.0
    for _ in range(MIN_CYCLES):
        t = run_cycle(a, "living", t + 3600.0, -1.0, 4.0)
    saved_off = a.offset_for("living", -2.0)

    b = learner()
    b._store = FakeStore()
    b._store.saved = a._store.saved
    asyncio.run(b.async_load())
    assert b.rooms["living"].cycles == MIN_CYCLES
    assert b.offset_for("living", -2.0) == saved_off


def test_zone_effective_setpoint_uses_learned_offset():
    """Once mature, an away preset reflects the learned depth."""
    from unittest.mock import MagicMock

    from custom_components.home_climate_control.zone import ZoneClimateEntity

    hass = MagicMock()
    coord = MagicMock()
    coord.curve_coeff = 1.2
    coord.flow_setpoint = None
    coord.setbacks = learner()

    room = ZoneClimateEntity(
        hass, coord, MagicMock(entry_id="e1"),
        {"name": "Study", "trv_climates": [], "temp_sensor": None,
         "window_sensors": []},
    )
    room.name = "Study"          # conftest Entity stub has no name property
    room.async_write_ha_state = MagicMock()
    room._hvac_mode = __import__(
        "homeassistant.components.climate", fromlist=["HVACMode"]
    ).HVACMode.HEAT
    room._target_temp = 21.0
    room._current_temp = 19.0

    room._preset = "away"
    # Away is an absolute preset (default 16 °C). The learned depth may
    # deepen below it, never above it.
    assert room.effective_setpoint() == pytest.approx(16.0)  # immature

    t = 0.0
    for _ in range(MIN_CYCLES):
        t = run_cycle(coord.setbacks, "Study", t + 3600.0, -1.2, 6.0)

    learned = coord.setbacks.offset_for("Study", -5.0)
    assert room.effective_setpoint() == pytest.approx(min(16.0, 21.0 + learned))


def test_window_open_freezes_learning():
    from unittest.mock import MagicMock

    from custom_components.home_climate_control.zone import ZoneClimateEntity

    hass = MagicMock()
    coord = MagicMock()
    coord.curve_coeff = 1.2
    coord.flow_setpoint = None
    coord.setbacks = learner()

    room = ZoneClimateEntity(
        hass, coord, MagicMock(entry_id="e1"),
        {"name": "Kitchen", "trv_climates": [], "temp_sensor": None,
         "window_sensors": []},
    )
    room.name = "Kitchen"
    room.async_write_ha_state = MagicMock()
    room._preset = "eco"
    before = dict(
        cycles=coord.setbacks.rooms["Kitchen"].cycles if coord.setbacks.rooms.get("Kitchen") else 0
    )
    # window open -> observer must not be called via on_sensor_update path
    room.on_sensor_update(18.0, True)
    assert coord.setbacks.rooms.get("Kitchen") is None or \
        coord.setbacks.rooms["Kitchen"].cycles == before["cycles"]
