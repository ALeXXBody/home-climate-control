"""Battery levels for the room hardware HCC already uses.

The integration owns no sensors of its own: TRVs and room temperature
sensors are user-provided entities. Their battery level is read from
either

  * a battery attribute on the entity itself (some climate/TRV entities
    expose ``battery_level`` / ``battery``), or
  * a ``device_class: battery`` sensor on the same HA device, resolved
    through the entity registry.

Only values that are actually known are reported — a room without a
readable battery simply renders nothing.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Entities report battery in one of these attributes.
_BATTERY_ATTRS = ("battery_level", "battery", "battery_percent")

# Below this the chip is marked low (panel colours it).
LOW_PCT = 20


def _pct(value: Any) -> int | None:
    """Normalise a battery reading to whole percent, or None."""
    if value is None:
        return None
    try:
        num = float(str(value).strip().rstrip("%"))
    except (TypeError, ValueError):
        return None
    if num != num or num < 0:  # NaN / negative
        return None
    # Some integrations report 0..1 instead of 0..100.
    if 0 < num <= 1:
        num *= 100
    if num > 100:
        return None
    return int(round(num))


def _attr_level(state: Any) -> int | None:
    attrs = getattr(state, "attributes", None) or {}
    for key in _BATTERY_ATTRS:
        level = _pct(attrs.get(key))
        if level is not None:
            return level
    return None


def _sibling_battery(hass: HomeAssistant, entity_id: str) -> int | None:
    """Battery level from a battery sensor on the same HA device."""
    try:
        from homeassistant.helpers import entity_registry as er
    except Exception:  # pragma: no cover - import guard
        return None
    try:
        registry = er.async_get(hass)
        entry = registry.async_get(entity_id)
        device_id = getattr(entry, "device_id", None)
        if not device_id:
            return None
        found: list[int] = []
        for sibling in er.async_entries_for_device(registry, device_id):
            stat = hass.states.get(sibling.entity_id)
            if stat is None:
                continue
            attrs = getattr(stat, "attributes", None) or {}
            if attrs.get("device_class") != "battery":
                continue
            level = _pct(stat.state)
            if level is not None:
                found.append(level)
        if not found:
            return None
        # A device may expose several battery sensors (pack + cell). The
        # weakest one is the useful number.
        return min(found)
    except Exception:  # noqa: BLE001 - never break status on registry weirdness
        _LOGGER.debug("battery lookup failed for %s", entity_id, exc_info=True)
        return None


def entity_battery(hass: HomeAssistant, entity_id: str | None) -> int | None:
    """Battery percent for one entity, from its attributes or its device."""
    if not entity_id:
        return None
    state = hass.states.get(entity_id)
    level = _attr_level(state) if state is not None else None
    if level is not None:
        return level
    return _sibling_battery(hass, entity_id)


def _label(hass: HomeAssistant, entity_id: str, fallback: str) -> str:
    state = hass.states.get(entity_id)
    name = (getattr(state, "attributes", None) or {}).get("friendly_name")
    return str(name or fallback)


def zone_batteries(
    hass: HomeAssistant,
    *,
    trvs: Any = (),
    temp_sensor: str | None = None,
) -> list[dict[str, Any]]:
    """Battery chips for one room: its TRV(s) and its temperature sensor."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entity_id in trvs or ():
        if not entity_id or entity_id in seen:
            continue
        seen.add(entity_id)
        level = entity_battery(hass, entity_id)
        if level is None:
            continue
        out.append(
            {
                "entity": entity_id,
                "kind": "trv",
                "name": _label(hass, entity_id, "TRV"),
                "level": level,
                "low": level <= LOW_PCT,
            }
        )
    if temp_sensor and temp_sensor not in seen:
        level = entity_battery(hass, temp_sensor)
        if level is not None:
            out.append(
                {
                    "entity": temp_sensor,
                    "kind": "temp",
                    "name": _label(hass, temp_sensor, "Temperature sensor"),
                    "level": level,
                    "low": level <= LOW_PCT,
                }
            )
    return out
