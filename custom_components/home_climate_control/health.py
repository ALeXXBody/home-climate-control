"""Radiator health flags — spot rooms whose heating can't keep up.

A radiator that is undersized, air-locked, sludged up, or behind a stuck
TRV betrays itself one way: the room demands heat for hours while running
at full flow and still never gets warm. Normal rooms show a sawtooth —
demand, reach target, rest. A sick room shows a flat line of unmet error.

This monitor watches each room's demand + deficit + flow saturation every
control tick:

    flagged  = demanding with deficit >= STRUGGLE_ERROR_C
               while flow is within FLOW_NEAR_MAX_K of maximum,
               continuously for struggle_after(outdoor)

Outdoor load scales the patience window: on a design-cold day every room
looks "struggling" for a while after a setback, so the flag waits longer
before crying wolf. Mild weather keeps the standard ~90 min threshold.

The flag clears as soon as the deficit closes (RECOVER_ERROR_C) or after
the room stops demanding for CLEAR_AFTER_S.
"""

from __future__ import annotations

import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)

STRUGGLE_ERROR_C = 0.8     # chronic deficit that counts as struggling
FLOW_NEAR_MAX_K = 2.0      # flow setpoint this close to max counts as saturated
STRUGGLE_AFTER_S = 90 * 60 # base patience at mild outdoor load
STRUGGLE_AFTER_MAX_S = 3 * 3600  # design-cold patience ceiling
RECOVER_ERROR_C = 0.3      # deficit small enough to clear the flag
CLEAR_AFTER_S = 10 * 60    # not demanding this long also clears it
DESIGN_OUTDOOR_DEFAULT = -10.0
COMFORT_REF_C = 20.0       # outdoor load reference (room-ish)

FLAG_STRUGGLING = "struggling"


def load_patience_s(
    outdoor: float | None,
    *,
    design_outdoor: float = DESIGN_OUTDOOR_DEFAULT,
    base_s: float = STRUGGLE_AFTER_S,
    max_s: float = STRUGGLE_AFTER_MAX_S,
) -> float:
    """Seconds of saturated deficit needed before raising the flag.

    load 0 (outdoor ≈ comfort) → base_s
    load 1 (outdoor ≈ design)  → up to max_s
    unknown outdoor            → base_s (unchanged legacy behaviour)
    """
    if outdoor is None:
        return base_s
    span = max(1.0, COMFORT_REF_C - float(design_outdoor))
    load = max(0.0, min(1.5, (COMFORT_REF_C - float(outdoor)) / span))
    # Mild → 1× base; design cold → ~2×; extreme → capped at max_s
    return min(max_s, base_s * (1.0 + load))


class _RoomState:
    __slots__ = ("streak_s", "idle_s", "flag")

    def __init__(self) -> None:
        self.streak_s = 0.0
        self.idle_s = 0.0
        self.flag: str | None = None


class RoomHealthMonitor:
    """Tracks per-room struggle streaks from control-tick observations."""

    def __init__(self) -> None:
        self.rooms: dict[str, _RoomState] = {}

    def _room(self, zone: str) -> _RoomState:
        return self.rooms.setdefault(zone, _RoomState())

    def feed(
        self,
        zone: str,
        ts: float,
        *,
        demanding: bool,
        deficit_c: float | None,
        flow_at_max: bool,
        tick_s: float,
        outdoor: float | None = None,
        design_outdoor: float = DESIGN_OUTDOOR_DEFAULT,
    ) -> bool:
        """One control-tick observation; returns True if currently flagged."""
        st = self._room(zone)
        need_s = load_patience_s(outdoor, design_outdoor=design_outdoor)

        if not demanding:
            st.idle_s += tick_s
            st.streak_s = 0.0
            if st.flag and st.idle_s >= CLEAR_AFTER_S:
                self._clear(zone, "no longer calling for heat")
            return bool(st.flag)

        st.idle_s = 0.0

        deficit_ok = deficit_c is not None and deficit_c >= STRUGGLE_ERROR_C
        if deficit_ok and flow_at_max:
            st.streak_s += tick_s
            if not st.flag and st.streak_s >= need_s:
                st.flag = FLAG_STRUGGLING
                _LOGGER.warning(
                    "'%s' struggles: %.1f °C short of target at full flow for %.0f min "
                    "(outdoor=%s, need ≥%.0f min) — check radiator size/bleeding/TRV",
                    zone,
                    deficit_c or 0.0,
                    st.streak_s / 60.0,
                    f"{outdoor:.1f}" if outdoor is not None else "?",
                    need_s / 60.0,
                )
        else:
            st.streak_s = max(0.0, st.streak_s - tick_s)

        if st.flag and deficit_c is not None and deficit_c <= RECOVER_ERROR_C:
            self._clear(zone, "reached its target again")
        return bool(st.flag)

    def _clear(self, zone: str, why: str) -> None:
        st = self._room(zone)
        st.flag = None
        st.streak_s = 0.0
        _LOGGER.info("'%s' health flag cleared (%s)", zone, why)

    def flag_for(self, zone: str) -> str | None:
        return self.rooms.get(zone).flag if zone in self.rooms else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "rooms": {
                name: {"flag": st.flag} for name, st in sorted(self.rooms.items())
            }
        }
