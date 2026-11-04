"""Battery chips for room hardware (TRV + temperature sensor)."""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace

import pytest

from custom_components.home_climate_control.battery import (
    LOW_PCT,
    _pct,
    entity_battery,
    zone_batteries,
)


def _state(state_val, **attrs):
    return SimpleNamespace(state=str(state_val), attributes=attrs)


class _Hass:
    def __init__(self, states):
        self.states = SimpleNamespace(get=lambda eid: states.get(eid))
        self._registry = None


class _RegEntry:
    def __init__(self, entity_id, device_id):
        self.entity_id = entity_id
        self.device_id = device_id


class _FakeRegistry:
    def __init__(self, by_entity):
        self.by_entity = dict(by_entity)

    def async_get(self, entity_id):
        device_id = self.by_entity.get(entity_id)
        return _RegEntry(entity_id, device_id) if device_id else None


@pytest.fixture
def registry(monkeypatch):
    """Install a fake entity registry module (conftest has none installed)."""
    mod = types.ModuleType("homeassistant.helpers.entity_registry")

    def install(hass, by_entity):
        """by_entity: {entity_id: device_id}"""
        hass._registry = _FakeRegistry(by_entity)

    mod.async_get = lambda hass: hass._registry
    mod.async_entries_for_device = lambda reg, device_id: [
        _RegEntry(eid, device_id)
        for eid, dev in reg.by_entity.items()
        if dev == device_id
    ]
    monkeypatch.setitem(sys.modules, "homeassistant.helpers.entity_registry", mod)
    return install


def test_pct_normalises_readings():
    assert _pct(87) == 87
    assert _pct("87") == 87
    assert _pct("87%") == 87
    assert _pct(0.87) == 87  # 0..1 fraction form
    assert _pct(100) == 100
    assert _pct(0) == 0
    assert _pct(None) is None
    assert _pct("unknown") is None
    assert _pct(-5) is None
    assert _pct(140) is None


def test_battery_from_entity_attribute():
    hass = _Hass({"climate.trv": _state("heat", battery_level=76)})
    assert entity_battery(hass, "climate.trv") == 76

    hass = _Hass({"sensor.t": _state("21.5", battery=0.62)})
    assert entity_battery(hass, "sensor.t") == 62


def test_battery_from_sibling_sensor_on_same_device(registry):
    hass = _Hass(
        {
            "climate.trv": _state("heat"),
            "sensor.trv_battery": _state("42", device_class="battery"),
            "sensor.trv_temperature": _state("21.4", device_class="temperature"),
        }
    )
    registry(hass, {
        "climate.trv": "dev1",
        "sensor.trv_battery": "dev1",
        "sensor.trv_temperature": "dev1",
    })
    assert entity_battery(hass, "climate.trv") == 42


def test_battery_takes_weakest_of_multiple_sensors(registry):
    hass = _Hass(
        {
            "sensor.probe": _state("18", device_class="battery"),
            "sensor.probe_pack": _state("73", device_class="battery"),
        }
    )
    registry(hass, {"sensor.probe": "dev1", "sensor.probe_pack": "dev1"})
    assert entity_battery(hass, "sensor.probe") == 18


def test_battery_unknown_entity_returns_none(registry):
    hass = _Hass({})
    registry(hass, {})
    assert entity_battery(hass, "climate.missing") is None
    assert entity_battery(hass, None) is None


def test_zone_batteries_orders_trv_then_temp_and_dedupes(registry):
    hass = _Hass(
        {
            "climate.trv": _state("heat", friendly_name="Office TRV", battery_level=76),
            "sensor.temp": _state("21.0", friendly_name="Office sensor", battery_level=54),
        }
    )
    registry(hass, {})
    out = zone_batteries(
        hass,
        trvs=["climate.trv", "climate.trv"],
        temp_sensor="sensor.temp",
    )
    assert [b["kind"] for b in out] == ["trv", "temp"]
    assert [b["level"] for b in out] == [76, 54]
    assert out[0]["name"] == "Office TRV"
    assert all(b["low"] is False for b in out)


def test_zone_batteries_marks_low_and_skips_unknown(registry):
    hass = _Hass(
        {
            "climate.trv": _state("heat", battery_level=LOW_PCT),
            "climate.dead": _state("heat"),
        }
    )
    registry(hass, {})
    out = zone_batteries(
        hass,
        trvs=["climate.trv", "climate.dead"],
        temp_sensor="sensor.absent",
    )
    assert len(out) == 1
    assert out[0]["kind"] == "trv"
    assert out[0]["low"] is True
