"""Optimal-start lead time — dead-time + recovery, not a fixed guess.

Every "start heating so the room is warm in time" decision is:

    lead = dead_time + deficit / warm_rate + margin

* dead_time  — transport lag until the room sensor moves (DeadTimeEstimator)
* warm_rate  — measured °C/h recovery (SetbackLearner / calibration)
* deficit    — how many °C below the comfort target we still are

Tier 0 uses this in two places without needing a calendar:

1. **Setback depth** — the allowed overnight drop is sized so that
   (recovery for that drop) + dead_time fits inside RECOVERY_TARGET_H.
2. **Reactive pre-heat** — while a room is still on away/eco, if catching
   up to the comfort setpoint would already take longer than the recovery
   window, raise demand now so the boiler is not starting from a cold
   hole the model never budgeted for.
"""

from __future__ import annotations

# Keep in lockstep with setback.RECOVERY_TARGET_H (imported by callers for
# display); duplicated here so this module stays HA-free / pure-logic.
RECOVERY_TARGET_H = 1.0
MIN_RECOVERY_H = 0.25          # never shrink the window below 15 min of pure rise
DEFAULT_DEAD_S = 5 * 60.0      # used only when no measurement yet
LEAD_MARGIN_S = 2 * 60.0       # small safety pad (valve lag, sensor lag)
MIN_WARM_CPH = 0.2
MAX_LEAD_S = 4 * 3600.0        # hard cap — never plan more than 4 h ahead
PREHEAT_ENTER_C = 0.4          # start catch-up when comfort deficit exceeds this
PREHEAT_EXIT_C = 0.15          # drop catch-up once nearly at comfort


def recovery_seconds(deficit_c: float, warm_cph: float | None) -> float:
    """Seconds of active warm-up needed for *deficit_c* at *warm_cph*."""
    if deficit_c is None or deficit_c <= 0:
        return 0.0
    rate = warm_cph if warm_cph is not None else None
    if rate is None or rate < MIN_WARM_CPH:
        return 0.0
    return float(deficit_c) / float(rate) * 3600.0


def lead_seconds(
    *,
    dead_s: float | None,
    warm_cph: float | None,
    deficit_c: float,
    margin_s: float = LEAD_MARGIN_S,
    default_dead_s: float = DEFAULT_DEAD_S,
) -> float:
    """Total CH-on lead before a comfort target time.

    Returns 0 when there is nothing to recover (already at/above target)
    or when we have no warm-rate to plan with (caller should not invent
    a multi-hour lead from dead-time alone).
    """
    if deficit_c is None or deficit_c <= 0:
        return 0.0
    rec = recovery_seconds(deficit_c, warm_cph)
    if rec <= 0.0 and (warm_cph is None or warm_cph < MIN_WARM_CPH):
        # No rate yet: report dead-time only so the UI can still show lag,
        # but keep it small (measurement or default).
        dt = float(dead_s) if dead_s is not None else default_dead_s
        return max(0.0, min(MAX_LEAD_S, dt + margin_s))
    dt = float(dead_s) if dead_s is not None else default_dead_s
    return max(0.0, min(MAX_LEAD_S, dt + rec + margin_s))


def recovery_window_h(dead_s: float | None) -> float:
    """Hours of pure temperature rise available inside RECOVERY_TARGET_H."""
    dead_h = (float(dead_s) if dead_s is not None else 0.0) / 3600.0
    return max(MIN_RECOVERY_H, RECOVERY_TARGET_H - max(0.0, dead_h))


def setback_depth_c(warm_cph: float, dead_s: float | None) -> float:
    """How deep a setback may go and still recover inside the target window."""
    rate = max(MIN_WARM_CPH, float(warm_cph))
    return rate * recovery_window_h(dead_s)


def should_preheat(
    *,
    in_setback: bool,
    comfort_deficit_c: float,
    dead_s: float | None,
    warm_cph: float | None,
    already_preheating: bool = False,
) -> bool:
    """True when a setback room must start catch-up heat now.

    Enter when lead time to comfort already exceeds the recovery window;
    exit with hysteresis once the comfort deficit is small.
    """
    if not in_setback:
        return False
    if comfort_deficit_c is None:
        return False
    # Leave preheat once close enough to comfort SP.
    if already_preheating and comfort_deficit_c <= PREHEAT_EXIT_C:
        return False
    if not already_preheating and comfort_deficit_c < PREHEAT_ENTER_C:
        return False
    if warm_cph is None or warm_cph < MIN_WARM_CPH:
        return False
    lead = lead_seconds(
        dead_s=dead_s,
        warm_cph=warm_cph,
        deficit_c=comfort_deficit_c,
        margin_s=LEAD_MARGIN_S,
    )
    # Budget = recovery window + the dead-time itself (same total as
    # RECOVERY_TARGET_H when dead-time is known).
    budget_s = RECOVERY_TARGET_H * 3600.0
    if already_preheating:
        # Stay on until lead fits comfortably inside the budget again.
        return lead > budget_s * 0.85
    return lead > budget_s
