"""Schedule → room preset follower.

Maps a Home Assistant entity (schedule / input_select / sensor / …) onto
HCC climate presets so night/away setbacks run from a real timetable
without phones or extra hardware.

Supported entity shapes
-----------------------
* ``schedule.*`` — HA schedule integration:
    state ``on``  → *on_preset*  (default comfort)
    state ``off`` → *off_preset* (default eco)
* Any entity whose state is already a preset name
  (``none`` / ``away`` / ``eco`` / ``comfort`` / ``boost``)
* Common aliases: home/present → comfort, not_home/away → away,
  night/sleep → eco, boost → boost

Manual preset changes on a room are sticky until the *schedule entity
itself* changes state again (next window), then the timetable resumes.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

_LOGGER = logging.getLogger(__name__)

from .const import (
    PRESET_AWAY,
    PRESET_BOOST,
    PRESET_COMFORT,
    PRESET_ECO,
    PRESET_NONE,
    ZONE_PRESETS,
)

# state text (lower) → preset
_ALIASES: dict[str, str] = {
    "none": PRESET_NONE,
    "off": PRESET_NONE,
    "away": PRESET_AWAY,
    "not_home": PRESET_AWAY,
    "leaving": PRESET_AWAY,
    "eco": PRESET_ECO,
    "night": PRESET_ECO,
    "sleep": PRESET_ECO,
    "comfort": PRESET_COMFORT,
    "home": PRESET_COMFORT,
    "present": PRESET_COMFORT,
    "on": PRESET_COMFORT,  # overridden for schedule.* by on/off presets
    "boost": PRESET_BOOST,
    "heat": PRESET_COMFORT,
}


def resolve_preset(
    state: str | None,
    *,
    entity_id: str | None = None,
    on_preset: str = PRESET_COMFORT,
    off_preset: str = PRESET_ECO,
) -> str | None:
    """Map an HA entity state string to an HCC preset, or None if unknown."""
    if state is None:
        return None
    text = str(state).strip().lower()
    if not text or text in ("unknown", "unavailable", "none", ""):
        # bare "none" is a valid preset — only skip empty/unavailable
        if text == "none":
            return PRESET_NONE
        return None

    # schedule.* uses on/off as window flags, not presets
    if entity_id and entity_id.startswith("schedule."):
        if text == "on":
            return on_preset if on_preset in ZONE_PRESETS else PRESET_COMFORT
        if text == "off":
            return off_preset if off_preset in ZONE_PRESETS else PRESET_ECO

    if text in ZONE_PRESETS:
        return text
    return _ALIASES.get(text)


class ScheduleFollower:
    """Applies a timetable entity to all smart zones."""

    def __init__(
        self,
        hass,
        *,
        entity_id: str | None = None,
        on_preset: str = PRESET_COMFORT,
        off_preset: str = PRESET_ECO,
        enabled: bool = True,
    ) -> None:
        self.hass = hass
        self.entity_id = (entity_id or "").strip() or None
        self.on_preset = on_preset if on_preset in ZONE_PRESETS else PRESET_COMFORT
        self.off_preset = off_preset if off_preset in ZONE_PRESETS else PRESET_ECO
        self.enabled = enabled and bool(self.entity_id)

        self.last_preset: str | None = None
        self.last_state: str | None = None
        self._unsub: Callable[[], None] | None = None
        self._zones: list = []

    def bind_zones(self, zones: list) -> None:
        self._zones = list(zones)

    def current_preset(self) -> str | None:
        if not self.enabled or not self.entity_id or self.hass is None:
            return None
        st = self.hass.states.get(self.entity_id)
        if st is None:
            return None
        return resolve_preset(
            st.state,
            entity_id=self.entity_id,
            on_preset=self.on_preset,
            off_preset=self.off_preset,
        )

    def apply(self, *, force: bool = False) -> str | None:
        """Push current schedule preset onto zones that follow the timetable.

        Returns the preset applied, or None if nothing changed / no schedule.
        """
        preset = self.current_preset()
        if preset is None:
            return None
        state_now = None
        if self.hass is not None and self.entity_id:
            st = self.hass.states.get(self.entity_id)
            state_now = st.state if st else None

        schedule_changed = force or (
            state_now is not None and state_now != self.last_state
        )
        self.last_state = state_now
        self.last_preset = preset

        if not schedule_changed and not force:
            # Still re-apply to zones that are following and drifted
            pass

        applied = 0
        for z in self._zones:
            if getattr(z, "heater_control", "smart") == "manual":
                continue
            # Sticky user override until the schedule entity changes.
            # Occupancy owns the room while everyone is away — don't fight it.
            src = getattr(z, "_preset_source", "schedule")
            if not schedule_changed and src == "user":
                continue
            if (
                not schedule_changed
                and src == "occupancy"
                and getattr(z, "_preset", None) in ("away",)
            ):
                continue
            setter = getattr(z, "apply_schedule_preset", None)
            if callable(setter):
                if setter(preset):
                    applied += 1
            else:
                # Fallback for bare test doubles
                if getattr(z, "_preset", None) != preset:
                    z._preset = preset
                    z._preset_source = "schedule"
                    applied += 1
        if applied:
            _LOGGER.debug(
                "Schedule %s → preset %s on %d room(s)",
                self.entity_id,
                preset,
                applied,
            )
        return preset

    def async_start(self) -> None:
        """Subscribe to schedule entity changes."""
        if not self.enabled or not self.entity_id or self.hass is None:
            return
        from homeassistant.helpers.event import async_track_state_change_event

        def _on_change(_event) -> None:
            try:
                self.apply(force=True)
            except Exception:  # noqa: BLE001
                _LOGGER.debug("schedule apply failed", exc_info=True)

        self._unsub = async_track_state_change_event(
            self.hass, [self.entity_id], _on_change
        )
        # Initial apply
        try:
            self.apply(force=True)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("schedule initial apply failed", exc_info=True)

    def async_stop(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "entity_id": self.entity_id,
            "on_preset": self.on_preset,
            "off_preset": self.off_preset,
            "last_preset": self.last_preset,
            "last_state": self.last_state,
        }
