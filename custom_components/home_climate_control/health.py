"""Radiator health flags — spot rooms whose heating can't keep up.

A radiator that is undersized, air-locked, sludged up, or behind a stuck
TRV betrays itself one way: the room demands heat for hours while running
at full flow and still never gets warm. Normal rooms show a sawtooth —
demand, reach target, rest. A sick room shows a flat line of unmet error.

This monitor watches each room's demand + deficit + flow saturation every
control tick:

    flagged  = demanding with deficit >= STRUGGLE_ERROR_C
               while flow is within FLOW_NEAR_MAX_K of maximum,
               continuously for STRUGGLE_AFTER_S

The flag clears as soon as the deficit closes (RECOVER_ERROR_C) or after
the room stops demanding for CLEAR_AFTER_S.

Messages are deliberately plain: the flag says WHAT to check (radiator
size, bleed valve, TRV), not just that something is wrong. The monitor is
pure logic — no persistence; a restart simply re-learns the pattern within
STRUGGLE_AFTER_S, which keeps state honest after config changes.
"""

from __future__ import annotations

import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)

STRUGGLE_ERROR_C = 0.8     # chronic deficit that counts as struggling
FLOW_NEAR_MAX_K = 2.0      # flow setpoint this close to max counts as saturated
STRUGGLE_AFTER_S = 90 * 60 # deficit must persist this long to raise the flag
RECOVER_ERROR_C = 0.3      # deficit small enough to clear the flag
CLEAR_AFTER_S = 10 * 60    # not demanding this long also clears it

FLAG_STRUGGLING = "struggling"


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
    ) -> bool:
        """One control-tick observation; returns True if currently flagged."""
        st = self._room(zone)

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
            if not st.flag and st.streak_s >= STRUGGLE_AFTER_S:
                st.flag = FLAG_STRUGGLING
                _LOGGER.warning(
                    "'%s' struggles: %.1f °C short of target at full flow for %.0f min "
                    "— check radiator size/bleeding/TRV",
                    zone,
                    deficit_c or 0.0,
                    st.streak_s / 60.0,
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
