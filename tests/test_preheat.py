"""Optimal-start lead time: dead-time + recovery, setback depth, reactive pre-heat."""

import pytest

from custom_components.home_climate_control.preheat import (
    RECOVERY_TARGET_H,
    lead_seconds,
    recovery_seconds,
    recovery_window_h,
    setback_depth_c,
    should_preheat,
)
from custom_components.home_climate_control.setback import (
    LEARNED_MAX_C,
    LEARNED_MIN_C,
    MIN_CYCLES,
    SetbackLearner,
)


def test_recovery_seconds_basic():
    # 2 °C at 4 °C/h → 0.5 h = 1800 s
    assert recovery_seconds(2.0, 4.0) == pytest.approx(1800.0)
    assert recovery_seconds(0.0, 4.0) == 0.0
    assert recovery_seconds(2.0, None) == 0.0
    assert recovery_seconds(2.0, 0.05) == 0.0  # below MIN_WARM


def test_lead_includes_dead_time_and_margin():
    # 2 °C @ 4 °C/h = 1800 s recovery + 600 s dead + 120 s margin
    lead = lead_seconds(dead_s=600.0, warm_cph=4.0, deficit_c=2.0)
    assert lead == pytest.approx(1800.0 + 600.0 + 120.0)
    # already warm
    assert lead_seconds(dead_s=600.0, warm_cph=4.0, deficit_c=0.0) == 0.0
    # no rate → small default-dead lead only
    bare = lead_seconds(dead_s=None, warm_cph=None, deficit_c=3.0)
    assert 0 < bare <= 10 * 60


def test_recovery_window_shrinks_with_dead_time():
    # 15 min dead → 0.75 h of pure rise left inside 1 h target
    assert recovery_window_h(15 * 60) == pytest.approx(0.75)
    # huge dead still leaves MIN_RECOVERY_H (0.25 h)
    assert recovery_window_h(2 * 3600) == pytest.approx(0.25)
    assert recovery_window_h(None) == pytest.approx(RECOVERY_TARGET_H)


def test_setback_depth_shallower_when_dead_time_long():
    fast = setback_depth_c(4.0, dead_s=0.0)          # 4 °C
    slow_pipe = setback_depth_c(4.0, dead_s=30 * 60)  # 4 * 0.5 = 2 °C
    assert fast == pytest.approx(4.0)
    assert slow_pipe == pytest.approx(2.0)
    assert slow_pipe < fast


def test_setback_offset_uses_dead_time():
    """Mature learner: longer dead-time → shallower (less negative) offset."""
    l = SetbackLearner(None)
    st = l._room("hall")
    st.warm_ema = 4.0
    st.cycles = MIN_CYCLES
    deep = l.offset_for("hall", fallback=-2.0, dead_time_s=0.0)
    shallow = l.offset_for("hall", fallback=-2.0, dead_time_s=30 * 60)
    assert deep == pytest.approx(-4.0)
    assert shallow == pytest.approx(-2.0)
    assert shallow > deep  # less negative
    # clamps still apply
    st.warm_ema = 50.0
    assert l.offset_for("hall", -2.0, dead_time_s=0.0) == LEARNED_MIN_C
    st.warm_ema = 0.3
    assert l.offset_for("hall", -2.0, dead_time_s=0.0) == LEARNED_MAX_C


def test_should_preheat_when_lead_exceeds_budget():
    # 4 °C hole @ 2 °C/h = 2 h recovery + 10 min dead >> 1 h budget
    assert should_preheat(
        in_setback=True,
        comfort_deficit_c=4.0,
        dead_s=10 * 60,
        warm_cph=2.0,
    )
    # tiny hole: no need
    assert not should_preheat(
        in_setback=True,
        comfort_deficit_c=0.2,
        dead_s=5 * 60,
        warm_cph=4.0,
    )
    # not in setback
    assert not should_preheat(
        in_setback=False,
        comfort_deficit_c=4.0,
        dead_s=10 * 60,
        warm_cph=2.0,
    )
    # hysteresis: stay on until deficit small
    assert should_preheat(
        in_setback=True,
        comfort_deficit_c=1.5,
        dead_s=10 * 60,
        warm_cph=2.0,
        already_preheating=True,
    )
    assert not should_preheat(
        in_setback=True,
        comfort_deficit_c=0.1,
        dead_s=10 * 60,
        warm_cph=2.0,
        already_preheating=True,
    )


def test_zone_preheat_drives_comfort_setpoint():
    """Integration: zone on away with large deficit arms pre-heat → comfort SP."""
    from homeassistant.components.climate import HVACMode

    class FakeDt:
        def seconds_for(self, name, fallback=None):
            return 10 * 60.0

    class FakeSb:
        def warm_rate_for(self, name):
            return 2.0  # slow

        def offset_for(self, name, fallback, dead_time_s=None):
            return -3.0

    class Coord:
        curve_coeff = 1.2
        flow_setpoint = None
        deadtime = FakeDt()
        setbacks = FakeSb()

    # Minimal zone without full HA climate setup
    from custom_components.home_climate_control.zone import ZoneClimateEntity

    z = object.__new__(ZoneClimateEntity)
    z.hass = None
    z.coordinator = Coord()
    z._attr_name = "Living"
    z._zone_cfg = {"name": "Living"}
    z._current_temp = 16.0
    z._target_temp = 21.0
    z._preset = "away"
    z._hvac_mode = HVACMode.HEAT
    z._window_open = False
    z.heater_control = "smart"
    z._preheat_active = False
    z._demand = 0.0
    z._pid_output = 0.0
    z._trv_entity = None
    z._trv_climates = []
    z._temp_sensor = None
    z._window_sensors = []
    z.floor = 0
    # PID stub
    class P:
        def reset(self):
            pass

        def update(self, e):
            return e * 2

    z.pid = P()

    assert z.wants_heat() is True
    assert z._preheat_active is True
    # During pre-heat, effective SP is the comfort target, not setback SP
    assert z.effective_setpoint() == pytest.approx(21.0)
    lead = z.lead_time_s(to_comfort=True)
    assert lead is not None and lead > 3600  # multi-hour catch-up


def test_zone_no_preheat_when_shallow_setback():
    from homeassistant.components.climate import HVACMode
    from custom_components.home_climate_control.zone import ZoneClimateEntity

    class FakeDt:
        def seconds_for(self, name, fallback=None):
            return 3 * 60.0

    class FakeSb:
        def warm_rate_for(self, name):
            return 5.0  # fast room

        def offset_for(self, name, fallback, dead_time_s=None):
            return -2.0

    class Coord:
        curve_coeff = 1.2
        flow_setpoint = None
        deadtime = FakeDt()
        setbacks = FakeSb()

    z = object.__new__(ZoneClimateEntity)
    z.hass = None
    z.coordinator = Coord()
    z._attr_name = "Bath"
    z._current_temp = 19.5  # only 1.5 below comfort 21
    z._target_temp = 21.0
    z._preset = "eco"
    z._hvac_mode = HVACMode.HEAT
    z._window_open = False
    z.heater_control = "smart"
    z._preheat_active = False
    z._demand = 0.0
    z._pid_output = 0.0
    z._trv_entity = None
    z.pid = type("P", (), {"reset": lambda s: None, "update": lambda s, e: 0})()

    # lead ≈ 3 min dead + 1.5/5 h + margin ≈ 3+18+2 = 23 min < 60 min budget
    assert z.wants_heat() is False or z._preheat_active is False
    assert z._preheat_active is False
    # Still on setback SP
    assert z.effective_setpoint() == pytest.approx(19.0)  # 21 + (-2)
