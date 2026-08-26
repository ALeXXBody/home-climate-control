"""Condensing optimization — pull flow down when return water is too hot.

Gas condensing boilers only hit peak efficiency when return temperature
stays below the dew point of the flue gas (~54–55 °C for natural gas).
A high return means the radiators are dumping heat too slowly for the
flow we commanded — the fix is a lower TSet, not more fire.

    if return > TARGET and rooms are not in deep deficit:
        flow_out = flow_in - min(MAX_PULL, gain * (return - TARGET))

Never raises flow. Never goes below min_flow. Skipped when any demanding
room has a large comfort deficit (comfort wins over efficiency).
"""

from __future__ import annotations

from typing import Any

# Natural-gas dew-point band; keep a little headroom under 55 °C.
RETURN_TARGET_C = 54.0
# °C of flow reduction per °C of return above target.
PULL_GAIN = 1.0
# Hard cap on a single-tick pull so we don't slam the boiler.
MAX_PULL_C = 8.0
# If the worst demanding room is this far below SP, do not pull down.
MAX_DEFICIT_FOR_PULL_C = 1.0


def condense_pull(
    flow_c: float,
    return_c: float | None,
    *,
    min_flow: float,
    worst_deficit_c: float | None = None,
    target_return: float = RETURN_TARGET_C,
    gain: float = PULL_GAIN,
    max_pull: float = MAX_PULL_C,
    max_deficit: float = MAX_DEFICIT_FOR_PULL_C,
) -> tuple[float, float]:
    """Return (adjusted_flow, pull_applied).

    pull_applied is ≥ 0 (°C shaved off). Zero when no action.
    """
    if return_c is None or flow_c is None:
        return flow_c, 0.0
    if worst_deficit_c is not None and worst_deficit_c > max_deficit:
        return flow_c, 0.0
    excess = float(return_c) - float(target_return)
    if excess <= 0.0:
        return flow_c, 0.0
    pull = min(float(max_pull), float(gain) * excess)
    adjusted = max(float(min_flow), float(flow_c) - pull)
    applied = float(flow_c) - adjusted
    return adjusted, applied


def as_dict_snapshot(
    *,
    return_c: float | None,
    pull_c: float,
    active: bool,
) -> dict[str, Any]:
    return {
        "return_c": None if return_c is None else round(return_c, 1),
        "target_c": RETURN_TARGET_C,
        "pull_c": round(pull_c, 2),
        "active": bool(active),
    }
