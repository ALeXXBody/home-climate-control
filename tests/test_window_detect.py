"""Slope-based open-window detection: fast drop trips, slow drift doesn't."""

from custom_components.home_climate_control.window_detect import (
    MAX_PAUSE_S,
    MIN_PAUSE_S,
    WINDOW_DROP_C,
    SlopeWindowDetector,
)

M = 60.0


def gentle_cooling(d, t0, rate_cph=0.8, minutes=30, start=21.0):
    """Feed a realistic structural cooling drift; return last observe() result."""
    res = False
    temp = start
    for i in range(1, minutes + 1):
        temp -= rate_cph * (60.0 / 3600.0)
        res = d.observe(t0 + i * M, temp)
    return res


def test_slow_structural_cooling_never_trips():
    d = SlopeWindowDetector()
    assert gentle_cooling(d, 1000.0, rate_cph=2.0) is False
    assert not d.open


def test_fast_dump_trips_detection():
    d = SlopeWindowDetector()
    gentle_cooling(d, 1000.0, minutes=10)
    # Window opens: ~2.4 °C gone within a few minutes -> trips fast.
    assert d.observe(1000.0 + 11 * M, 20.5 - WINDOW_DROP_C) is True
    assert d.open


def test_pause_releases_after_temperature_stabilises():
    d = SlopeWindowDetector()
    gentle_cooling(d, 1000.0, minutes=10)
    d.observe(1000.0 + 12 * M, 19.9)
    assert d.open
    # Window closed ~minute 14; temperature bottoms out then creeps back.
    # Close becomes possible once MIN_PAUSE_S has passed AND the recent
    # slope is flat/rising.
    d.observe(1000.0 + 14 * M, 19.7)
    d.observe(1000.0 + 16 * M, 19.70)
    d.observe(1000.0 + 18 * M, 19.72)
    d.observe(1000.0 + 20 * M, 19.74)
    assert d.observe(1000.0 + 22 * M, 19.76) is False


def test_pause_persists_while_still_falling():
    d = SlopeWindowDetector()
    gentle_cooling(d, 1000.0, minutes=10)
    d.observe(1000.0 + 12 * M, 19.9)
    t = 1000.0 + 15 * M
    temp = 19.7
    # Keep falling at 3 °C/h well past the minimum pause.
    while t < 1000.0 + (MIN_PAUSE_S / M + 16) * M:
        t += M
        temp -= 0.05
        assert d.observe(t, temp) is True


def test_hard_cap_clears_a_stuck_pause():
    d = SlopeWindowDetector()
    gentle_cooling(d, 1000.0, minutes=10)
    d.observe(1000.0 + 12 * M, 19.9)
    # Sensor keeps creeping lower forever -> the cap must clear it anyway.
    t = 1000.0 + 13 * M
    temp = 19.8
    res = True
    while t < 1000.0 + (MAX_PAUSE_S / M + 15) * M:
        t += 5 * M
        temp -= 0.01
        res = d.observe(t, temp)
    assert res is False


def test_sensor_gap_discards_stale_history():
    d = SlopeWindowDetector()
    gentle_cooling(d, 1000.0, minutes=10)
    # One huge outage: next sample arrives an hour later, much colder.
    # A stale cliff from before the outage must NOT count as a window event.
    assert d.observe(1000.0 + 70 * M, 18.0) is False
    assert not d.open


def test_rearm_after_close_requires_new_context():
    d = SlopeWindowDetector()
    gentle_cooling(d, 1000.0, minutes=10)
    d.observe(1000.0 + 12 * M, 19.9)          # trip
    d.observe(1000.0 + 14 * M, 19.7)
    d.observe(1000.0 + 16 * M, 19.70)
    d.observe(1000.0 + 18 * M, 19.72)
    d.observe(1000.0 + 20 * M, 19.74)
    assert d.observe(1000.0 + 22 * M, 19.76) is False   # stable -> close
    assert not d.open
    # Dumping hard again re-trips once fresh samples accumulate.
    d.observe(1000.0 + 25 * M, 19.4)
    d.observe(1000.0 + 27 * M, 19.15)
    assert d.observe(1000.0 + 29 * M, 18.95) is True


# ------------------------------------------------------------------ wiring

def _make_room(window_sensors):
    from unittest.mock import MagicMock
    from custom_components.home_climate_control.zone import ZoneClimateEntity

    hass = MagicMock()
    coord = MagicMock()
    coord.curve_coeff = 1.2
    coord.flow_setpoint = 45.0
    entry = MagicMock()
    entry.entry_id = "e1"
    room = ZoneClimateEntity(
        hass,
        coord,
        entry,
        {
            "name": "Kitchen",
            "trv_climates": ["climate.kitchen_trv"],
            "temp_sensor": None,
            "window_sensors": window_sensors,
        },
    )
    room.async_write_ha_state = MagicMock()
    return room


def test_zone_without_contact_sensor_gets_slope_detector(monkeypatch):
    import time as _time
    from custom_components.home_climate_control.window_detect import (
        MIN_PAUSE_S,
        WINDOW_DROP_C,
    )

    clock = {"t": 1000.0}
    monkeypatch.setattr(_time, "time", lambda: clock["t"])

    room = _make_room([])
    assert room._slope_detector is not None
    from homeassistant.components.climate import HVACMode

    room._hvac_mode = HVACMode.HEAT
    room._target_temp = 21.0

    def upd(t):
        clock["t"] += 120
        room.on_sensor_update(t, None)

    # gentle drift then a hard dump -> pause engages, demand stops
    for _ in range(10):
        upd(20.9)
    assert room.wants_heat() is True
    for t in (20.4, 19.9, 19.4):
        upd(t)
    assert room._window_open is True
    assert room.wants_heat() is False
    # recovery: flat-ish samples past MIN_PAUSE -> heat allowed again
    for dt in range(6):
        upd(19.4 + dt * 0.02)
    clock["t"] += MIN_PAUSE_S
    upd(19.55)
    assert room._window_open is False


def test_zone_with_contact_sensor_keeps_real_path():
    room = _make_room(["binary_sensor.kitchen_door"])
    assert room._slope_detector is None
