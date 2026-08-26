"""Occupancy → away/home presets from phone device trackers.

Optional Tier-2 feature. When enabled in integration options, HCC watches
one or more HA entities (``device_tracker.*``, ``person.*``,
``binary_sensor.*`` presence) and:

* **All away** → apply *away_preset* (default ``away``) to every smart room
* **Anyone home** → apply *home_preset* (default ``comfort``), or hand
  control back to the schedule follower when one is configured

Manual preset changes stay sticky until occupancy *or* the schedule window
changes (same sticky model as ``schedule.py``).

Presence states treated as **home**:
  ``home``, ``on``, ``true``, ``1``, ``present``, ``arrived``
Presence states treated as **away**:
  ``not_home``, ``away``, ``off``, ``false``, ``0``, ``left``
Unavailable/unknown trackers are ignored (not counted as away).
"""

from __future__ import annotations

import logging
from typing import Any, Callable

_LOGGER = logging.getLogger(__name__)

from .const import PRESET_AWAY, PRESET_COMFORT, ZONE_PRESETS

_HOME_STATES = frozenset(
    {"home", "on", "true", "1", "present", "arrived", "just_arrived"}
)
_AWAY_STATES = frozenset(
    {"not_home", "away", "off", "false", "0", "left", "just_left"}
)


def is_home_state(state: str | None) -> bool | None:
    """True=home, False=away, None=unknown/ignore."""
    if state is None:
        return None
    text = str(state).strip().lower()
    if not text or text in ("unknown", "unavailable", "none", ""):
        return None
    if text in _HOME_STATES:
        return True
    if text in _AWAY_STATES:
        return False
    return None


def aggregate_presence(states: list[str | None]) -> str | None:
    """Combine tracker states → ``home`` / ``away`` / None (no data)."""
    saw_any = False
    any_home = False
    for s in states:
        flag = is_home_state(s)
        if flag is None:
            continue
        saw_any = True
        if flag:
            any_home = True
    if not saw_any:
        return None
    return "home" if any_home else "away"


class OccupancyFollower:
    """Applies presence-based presets to smart zones."""

    def __init__(
        self,
        hass,
        *,
        entity_ids: list[str] | None = None,
        away_preset: str = PRESET_AWAY,
        home_preset: str = PRESET_COMFORT,
        enabled: bool = False,
        schedule=None,
    ) -> None:
        self.hass = hass
        ids = [e.strip() for e in (entity_ids or []) if e and str(e).strip()]
        self.entity_ids = ids
        self.away_preset = away_preset if away_preset in ZONE_PRESETS else PRESET_AWAY
        self.home_preset = home_preset if home_preset in ZONE_PRESETS else PRESET_COMFORT
        self.enabled = bool(enabled) and bool(ids)
        self.schedule = schedule

        self.last_presence: str | None = None  # home | away
        self.last_preset: str | None = None
        self._unsub: Callable[[], None] | None = None
        self._zones: list = []

    def bind_zones(self, zones: list) -> None:
        self._zones = list(zones)

    def set_schedule(self, schedule) -> None:
        self.schedule = schedule

    def current_presence(self) -> str | None:
        if not self.enabled or not self.entity_ids or self.hass is None:
            return None
        states: list[str | None] = []
        for eid in self.entity_ids:
            st = self.hass.states.get(eid)
            states.append(st.state if st is not None else None)
        return aggregate_presence(states)

    def _preset_for(self, presence: str) -> str | None:
        if presence == "away":
            return self.away_preset
        if presence == "home":
            # Prefer live schedule when home so night eco still works.
            if self.schedule is not None and getattr(self.schedule, "enabled", False):
                sp = self.schedule.current_preset()
                if sp is not None:
                    return sp
            return self.home_preset
        return None

    def apply(self, *, force: bool = False) -> str | None:
        """Push presence-driven preset. Returns preset applied or None."""
        if not self.enabled:
            return None
        presence = self.current_presence()
        if presence is None:
            return None
        presence_changed = force or presence != self.last_presence
        self.last_presence = presence
        preset = self._preset_for(presence)
        if preset is None:
            return None
        self.last_preset = preset

        applied = 0
        for z in self._zones:
            if getattr(z, "heater_control", "smart") == "manual":
                continue
            # Sticky user override until presence changes.
            if (
                not presence_changed
                and getattr(z, "_preset_source", "schedule") == "user"
            ):
                continue
            setter = getattr(z, "apply_schedule_preset", None)
            if callable(setter):
                # Reuse schedule applier; mark source as occupancy.
                if setter(preset):
                    z._preset_source = "occupancy"
                    applied += 1
                elif getattr(z, "_preset", None) == preset:
                    z._preset_source = "occupancy"
            else:
                if getattr(z, "_preset", None) != preset:
                    z._preset = preset
                    z._preset_source = "occupancy"
                    applied += 1
        if applied:
            _LOGGER.debug(
                "Occupancy %s → preset %s on %d room(s)",
                presence,
                preset,
                applied,
            )
        return preset

    def async_start(self) -> None:
        if not self.enabled or not self.entity_ids or self.hass is None:
            return
        from homeassistant.helpers.event import async_track_state_change_event

        def _on_change(_event) -> None:
            try:
                self.apply(force=True)
            except Exception:  # noqa: BLE001
                _LOGGER.debug("occupancy apply failed", exc_info=True)

        self._unsub = async_track_state_change_event(
            self.hass, list(self.entity_ids), _on_change
        )
        try:
            self.apply(force=True)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("occupancy initial apply failed", exc_info=True)

    def async_stop(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "entity_ids": list(self.entity_ids),
            "away_preset": self.away_preset,
            "home_preset": self.home_preset,
            "last_presence": self.last_presence,
            "last_preset": self.last_preset,
        }
