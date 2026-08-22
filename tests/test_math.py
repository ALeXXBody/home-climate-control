"""Unit tests for pure math helpers (no Home Assistant required)."""

from __future__ import annotations

import sys
from pathlib import Path

# Allow importing the component package without installing HA.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_components" / "home_climate_control"))

from heating_curve import clamp, flow_for_outdoor  # noqa: E402
from pid import PID  # noqa: E402


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


def test_pid_responds_to_error():
    pid = PID(kp=10.0, ki=0.0, kd=0.0, output_min=0, output_max=40)
    out = pid.update(2.0, now=0.0)
    assert out == 20.0  # first sample uses P only
    out2 = pid.update(2.0, now=60.0)
    assert out2 == 20.0


def test_pid_integral_builds():
    pid = PID(kp=0.0, ki=1.0, kd=0.0, output_min=0, output_max=40, integral_clamp=15)
    pid.update(1.0, now=0.0)
    out = pid.update(1.0, now=5.0)
    assert out == 5.0  # integral 1*5 * ki 1


if __name__ == "__main__":
    test_clamp()
    test_flow_rises_when_colder_outside()
    test_flow_clamped_to_max()
    test_pid_responds_to_error()
    test_pid_integral_builds()
    print("OK")
