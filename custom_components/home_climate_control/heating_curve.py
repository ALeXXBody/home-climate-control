"""Heating curve: weather compensation.

flow_target = room_setpoint + coeff * (room_setpoint - outdoor)
normalized against the design outdoor temperature so that coeff=1.0 means
"full design load at design outdoor temp".
"""

from __future__ import annotations


def flow_for_outdoor(
    room_setpoint: float,
    outdoor_temp: float,
    coeff: float,
    min_flow: float,
    max_flow: float,
    design_outdoor: float = -10.0,
) -> float:
    """Return the boiler flow-water setpoint for current conditions."""
    if outdoor_temp is None:
        outdoor_temp = design_outdoor

    # Fraction of design load this weather represents (0..1+).
    delta_room = room_setpoint - design_outdoor
    if delta_room <= 0:
        return min_flow
    load_fraction = (room_setpoint - outdoor_temp) / delta_room
    load_fraction = max(0.0, load_fraction)

    raw = room_setpoint + coeff * load_fraction * 20.0
    return clamp(raw, min_flow, max_flow)


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))
