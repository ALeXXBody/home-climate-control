"""Radiator output metering (Tier 4).

With a per-room nominal radiator output (kW at the standard ΔT50 rating
point) and the boiler's real flow/return temperatures, the actual heat
output of the radiator right now follows the radiator equation:

    Q = nominal_kw × (ΔT / 50)^1.3
    ΔT = (flow + return) / 2 − room

This turns the OpenTherm data HCC already has into per-room "true
radiator watts" — the closest thing to a radiator heat meter without
adding hardware.
"""

from __future__ import annotations

NOMINAL_DELTA_T = 50.0
RADIATOR_EXPONENT = 1.3


def radiator_output_kw(
    nominal_kw: float | None,
    flow_c: float | None,
    return_c: float | None,
    room_c: float | None,
) -> float | None:
    """Current radiator output in kW, or None when data is missing."""
    if nominal_kw is None or nominal_kw <= 0:
        return None
    if flow_c is None or return_c is None or room_c is None:
        return None
    dt = (float(flow_c) + float(return_c)) / 2.0 - float(room_c)
    if dt <= 0:
        return 0.0
    return round(float(nominal_kw) * (dt / NOMINAL_DELTA_T) ** RADIATOR_EXPONENT, 2)
