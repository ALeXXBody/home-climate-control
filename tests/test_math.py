"""Tests for heating curve and PID (no Home Assistant)."""

from __future__ import annotations

from home_climate_control.heating_curve import clamp, flow_for_outdoor
from home_climate_control.pid import PID


def test_clamp():
    assert clamp(5, 0, 10) == 5
    assert clamp(-1, 0, 10) == 0
    assert clamp(99, 0, 10) == 10


def test_flow_rises_when_colder_outside():
    warm = flow_for_outdoor(20.0, outdoor_temp=10.0, coeff=1.2, min_flow=25, max_flow=75)
    cold = flow_for_outdoor(20.0, outdoor_temp=-5.0, coeff=1.2, min_flow=25, max_flow=75)
    assert cold > warm
    assert 25 <= warm <= 75
    assert 25 <= cold <= 75


def test_flow_clamped_to_max():
    hot = flow_for_outdoor(22.0, outdoor_temp=-20.0, coeff=3.0, min_flow=25, max_flow=55)
    assert hot == 55


def test_flow_clamped_to_min_when_warm():
    mild = flow_for_outdoor(20.0, outdoor_temp=25.0, coeff=1.0, min_flow=30, max_flow=75)
    assert mild == 30


def test_higher_coeff_raises_flow():
    low = flow_for_outdoor(20.0, outdoor_temp=0.0, coeff=0.8, min_flow=25, max_flow=75)
    high = flow_for_outdoor(20.0, outdoor_temp=0.0, coeff=1.8, min_flow=25, max_flow=75)
    assert high > low


def test_pid_responds_to_error():
    pid = PID(kp=10.0, ki=0.0, kd=0.0, output_min=0, output_max=40)
    out = pid.update(2.0, now=0.0)
    assert out == 20.0
    out2 = pid.update(2.0, now=60.0)
    assert out2 == 20.0


def test_pid_integral_builds():
    pid = PID(kp=0.0, ki=1.0, kd=0.0, output_min=0, output_max=40, integral_clamp=15)
    pid.update(1.0, now=0.0)
    out = pid.update(1.0, now=5.0)
    assert out == 5.0


def test_pid_output_clamped():
    pid = PID(kp=100.0, ki=0.0, kd=0.0, output_min=0, output_max=25)
    assert pid.update(10.0, now=0.0) == 25.0


def test_pid_reset_clears_state():
    pid = PID(kp=0.0, ki=1.0, kd=0.0, output_min=0, output_max=40, integral_clamp=15)
    pid.update(1.0, now=0.0)
    pid.update(1.0, now=10.0)
    assert pid.integral > 0
    pid.reset()
    assert pid.integral == 0.0
