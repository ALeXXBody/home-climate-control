"""Low-load duty cycling — PWM the burner when demand is below min modulation.

A modulating boiler that is asked for 8% fire while its floor is 20% will
either short-cycle on its own thermostat or run continuous overshoot.
Instead we honour the *average* load with long on/off slices:

    fraction = required_mod / min_mod          # 0..1
    on_s     = max(MIN_ON,  period * fraction)
    off_s    = max(MIN_OFF, period * (1 - fraction))

The period is derived so both floors are respected:

    period = MIN_ON / fraction           when fraction is high
    period = MIN_OFF / (1 - fraction)    when fraction is low
    period = MIN_ON + MIN_OFF            at 50%

Pure logic: no Home Assistant imports.
"""

from __future__ import annotations

from typing import Any

from .const import (
    DEFAULT_BOILER_MIN_MODULATION,
    DUTY_CYCLE_MIN_OFF_SECONDS,
    DUTY_CYCLE_MIN_ON_SECONDS,
)

# Demand sum 0..N maps to an estimated required modulation %.
# One full-demand room ≈ 100% of the boiler's useful range for duty math.
DEMAND_TO_MOD_PCT = 100.0


class DutyCycler:
    """Time-slices CH enable when required load < boiler min modulation."""

    def __init__(
        self,
        *,
        min_mod_pct: float = DEFAULT_BOILER_MIN_MODULATION,
        min_on_s: float = DUTY_CYCLE_MIN_ON_SECONDS,
        min_off_s: float = DUTY_CYCLE_MIN_OFF_SECONDS,
        enabled: bool = True,
    ) -> None:
        self.min_mod_pct = max(5.0, float(min_mod_pct))
        self.min_on_s = max(60.0, float(min_on_s))
        self.min_off_s = max(60.0, float(min_off_s))
        self.enabled = enabled

        self.active = False          # currently in duty-cycle mode
        self.phase_on = False        # current PWM phase
        self._phase_started: float | None = None
        self.fraction = 1.0          # last computed duty fraction 0..1
        self.required_mod_pct = 0.0
        self.last_reason = ""

    def reset(self) -> None:
        self.active = False
        self.phase_on = False
        self._phase_started = None
        self.fraction = 1.0
        self.required_mod_pct = 0.0
        self.last_reason = ""

    @staticmethod
    def required_mod_from_demand(total_demand: float) -> float:
        """Map aggregate zone demand (sum of 0..1) to a 0..100% load estimate."""
        return max(0.0, min(100.0, float(total_demand) * DEMAND_TO_MOD_PCT))

    def _period_s(self, fraction: float) -> tuple[float, float]:
        """Return (on_s, off_s) for a duty fraction in (0, 1)."""
        f = max(0.05, min(0.95, fraction))
        # Honour both floors: stretch the period as needed.
        on_s = max(self.min_on_s, self.min_on_s)  # baseline
        off_s = max(self.min_off_s, self.min_off_s)
        # Scale so on/(on+off) ≈ f while never dropping below floors.
        # on = f * T, off = (1-f) * T  →  T >= min_on/f and T >= min_off/(1-f)
        t_on = self.min_on_s / f
        t_off = self.min_off_s / (1.0 - f)
        period = max(t_on, t_off, self.min_on_s + self.min_off_s)
        on_s = max(self.min_on_s, period * f)
        off_s = max(self.min_off_s, period * (1.0 - f))
        return on_s, off_s

    def apply(
        self,
        *,
        want_heat: bool,
        total_demand: float,
        now: float,
    ) -> tuple[bool, str]:
        """Gate *want_heat* through the low-load PWM.

        Returns (desired_ch, reason). When load ≥ min modulation or there is
        no demand, passes through unchanged and leaves duty mode.
        """
        if not self.enabled or not want_heat:
            if self.active:
                self.reset()
            self.required_mod_pct = 0.0
            self.last_reason = "off" if not want_heat else "disabled"
            return want_heat, self.last_reason

        req = self.required_mod_from_demand(total_demand)
        self.required_mod_pct = req

        if req >= self.min_mod_pct - 0.5:
            # Enough continuous load — leave duty mode.
            if self.active:
                self.reset()
            self.fraction = 1.0
            self.last_reason = "continuous"
            return True, self.last_reason

        if req < 1.0:
            # Essentially no load.
            if self.active:
                self.reset()
            self.fraction = 0.0
            self.last_reason = "no load"
            return False, self.last_reason

        fraction = req / self.min_mod_pct
        self.fraction = fraction
        on_s, off_s = self._period_s(fraction)

        if not self.active:
            # Enter duty mode on the ON phase so a cold start still fires.
            self.active = True
            self.phase_on = True
            self._phase_started = now
            self.last_reason = f"duty enter on ({fraction * 100:.0f}%)"
            return True, self.last_reason

        started = self._phase_started
        if started is None:
            started = now
            self._phase_started = now
        elapsed = now - started
        if self.phase_on:
            if elapsed >= on_s:
                self.phase_on = False
                self._phase_started = now
                self.last_reason = f"duty off ({fraction * 100:.0f}%)"
                return False, self.last_reason
            self.last_reason = f"duty on ({fraction * 100:.0f}%)"
            return True, self.last_reason

        if elapsed >= off_s:
            self.phase_on = True
            self._phase_started = now
            self.last_reason = f"duty on ({fraction * 100:.0f}%)"
            return True, self.last_reason
        self.last_reason = f"duty off ({fraction * 100:.0f}%)"
        return False, self.last_reason

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "active": self.active,
            "phase": "on" if self.phase_on else ("off" if self.active else "idle"),
            "fraction": round(self.fraction, 3),
            "required_mod_pct": round(self.required_mod_pct, 1),
            "min_mod_pct": self.min_mod_pct,
            "min_on_s": self.min_on_s,
            "min_off_s": self.min_off_s,
            "last_reason": self.last_reason,
        }
