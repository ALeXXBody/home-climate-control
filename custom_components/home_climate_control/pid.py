"""PID controller with anti-windup.

The controller output is a *flow temperature contribution* (°C) rather than a
0-100% signal, because on an OpenTherm boiler the cheapest way to satisfy a
room deficit is to raise/lower flow water temperature, not to bang on/off.
"""

from __future__ import annotations

import time


class PID:
    """Incremental PID producing °C of flow-temperature adjustment."""

    def __init__(
        self,
        kp: float,
        ki: float,
        kd: float,
        output_min: float = 0.0,
        output_max: float = 40.0,
        integral_clamp: float = 15.0,
    ) -> None:
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.output_min = output_min
        self.output_max = output_max
        self.integral_clamp = integral_clamp
        self._integral = 0.0
        self._prev_error: float | None = None
        self._last_time: float | None = None

    def reset(self) -> None:
        self._integral = 0.0
        self._prev_error = None
        self._last_time = None

    def update(self, error: float, now: float | None = None) -> float:
        """Advance one control step. error = setpoint - current (°C)."""
        t = now if now is not None else time.monotonic()

        if self._last_time is None or self._prev_error is None:
            self._prev_error = error
            self._last_time = t
            return clamp(self.kp * error, self.output_min, self.output_max)

        dt = max(t - self._last_time, 1e-6)

        proportional = self.kp * error
        self._integral += error * dt
        self._integral = max(
            -self.integral_clamp, min(self.integral_clamp, self._integral)
        )
        integral = self.ki * self._integral
        derivative = self.kd * (error - self._prev_error) / dt

        self._prev_error = error
        self._last_time = t
        return clamp(proportional + integral + derivative, self.output_min, self.output_max)

    @property
    def integral(self) -> float:
        return self._integral


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))
