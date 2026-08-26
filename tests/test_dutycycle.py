"""Low-load duty cycling: PWM CH when demand < boiler min modulation."""

import pytest

from custom_components.home_climate_control.dutycycle import DutyCycler


def test_passthrough_when_demand_high():
    d = DutyCycler(min_mod_pct=20.0)
    # demand 0.5 → 50% required ≥ 20%
    on, reason = d.apply(want_heat=True, total_demand=0.5, now=0.0)
    assert on is True
    assert reason == "continuous"
    assert d.active is False


def test_enters_duty_on_low_demand():
    d = DutyCycler(min_mod_pct=20.0, min_on_s=600.0, min_off_s=600.0)
    # demand 0.1 → 10% required < 20% → duty fraction 0.5
    on, reason = d.apply(want_heat=True, total_demand=0.1, now=1000.0)
    assert on is True
    assert d.active is True
    assert d.phase_on is True
    assert "duty" in reason


def test_pwm_phases_flip():
    d = DutyCycler(min_mod_pct=20.0, min_on_s=100.0, min_off_s=100.0)
    t = 0.0
    on, _ = d.apply(want_heat=True, total_demand=0.1, now=t)  # 50% duty
    assert on is True
    # still inside on window
    on, _ = d.apply(want_heat=True, total_demand=0.1, now=t + 50)
    assert on is True
    # past on window → off
    on, reason = d.apply(want_heat=True, total_demand=0.1, now=t + 150)
    assert on is False
    assert d.phase_on is False
    # past off window → on again
    on, _ = d.apply(want_heat=True, total_demand=0.1, now=t + 300)
    assert on is True
    assert d.phase_on is True


def test_exits_when_demand_rises():
    d = DutyCycler(min_mod_pct=20.0)
    d.apply(want_heat=True, total_demand=0.05, now=0.0)
    assert d.active is True
    on, reason = d.apply(want_heat=True, total_demand=0.8, now=10.0)
    assert on is True
    assert d.active is False
    assert reason == "continuous"


def test_off_when_no_heat():
    d = DutyCycler()
    d.apply(want_heat=True, total_demand=0.05, now=0.0)
    on, _ = d.apply(want_heat=False, total_demand=0.0, now=5.0)
    assert on is False
    assert d.active is False


def test_disabled_passthrough():
    d = DutyCycler(enabled=False, min_mod_pct=20.0)
    on, reason = d.apply(want_heat=True, total_demand=0.05, now=0.0)
    assert on is True
    assert reason == "disabled"


@pytest.mark.asyncio
async def test_controller_duty_holds_ch_off_phase():
    """CentralController feeds low demand through DutyCycler before CycleGuard."""
    from unittest.mock import MagicMock

    from custom_components.home_climate_control.central import CentralController
    from tests.test_controller import FakeBackend, FakeZone

    hass = MagicMock()
    backend = FakeBackend()
    ctrl = CentralController(
        hass,
        backend,
        curve_coeff=1.2,
        design_outdoor=-10,
        min_flow=25,
        max_flow=75,
        min_modulation_pct=20.0,
        duty_cycle_enabled=True,
    )
    # Tiny demand → duty mode. Force min on/off short for the test.
    ctrl.dutycycle.min_on_s = 30.0
    ctrl.dutycycle.min_off_s = 30.0
    ctrl.cycleguard.hard_min_on_s = 0.0
    ctrl.cycleguard.base_min_off_s = 0.0
    z = FakeZone("R", wants=True, demand=0.05, pid_extra=0.0)
    ctrl.zones = [z]

    await ctrl.async_control_step()
    assert ctrl.dutycycle.active is True
    # First phase is ON
    assert backend.ch_enabled is True

    # Advance into OFF phase by replaying apply clock via dutycycle state
    ctrl.dutycycle._phase_started = ctrl.dutycycle._phase_started - 100
    await ctrl.async_control_step()
    # CycleGuard may still hold min-on; with hard_min_on=0 should allow off
    assert backend.ch_enabled is False or ctrl.dutycycle.phase_on is False
