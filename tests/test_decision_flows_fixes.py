"""Decision-flows pass: restore validation, gas bridging, unload tie."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from custom_components.home_climate_control.__init__ import (
    _validate_restored_zones,
)
from custom_components.home_climate_control.gasmeter import GasMeter


def test_restored_zone_keeps_valid_fields():
    zones = [{
        "name": "Bath", "heat_control": "floor",
        "floor_loop_entity": "switch.bath_loop",
        "temp_sensor": "sensor.bath_temp",
        "floor": 1, "setpoint": 21.0,
        "lux_sensor": "sensor.lux",
        "poison": "drop-me",
    }]
    out = _validate_restored_zones(zones)
    assert len(out) == 1
    z = out[0]
    assert z["name"] == "Bath"
    assert z["floor_loop_entity"] == "switch.bath_loop"
    assert z["temp_sensor"] == "sensor.bath_temp"
    assert z["floor"] == 1
    assert "poison" not in z


def test_restored_zone_drops_injection():
    zones = [{
        "name": "x",
        "floor_surface_max": 999,
        "temp_sensor": "not-a-sensor",
        "lux_sensor": 1234,
        "floor_loop_entity": None,
        "heat_control": "floor",
    }]
    out = _validate_restored_zones(zones)
    z = out[0]
    assert "floor_surface_max" not in z
    assert "temp_sensor" not in z
    assert "lux_sensor" not in z
    assert z["heat_control"] == "manual"   # floor without loop → observed


def test_restored_nameless_entry_dropped():
    out = _validate_restored_zones([{"temp_sensor": "sensor.x"}])
    assert out == []


def test_gas_persists_and_drops_last_t():
    """`last_t` persisted + loader drops long dead gaps with a log."""
    import time as _t
    g = GasMeter(MagicMock())
    g._store = None
    g._last_t = None
    now = _t.time()
    g._last_t = now - 200.0           # within the 300 s cap
    kwh = g.feed(now=now, flame_on=True, modulation=50,
                 flow_temp=60, return_temp=40)
    assert kwh > 0                     # short gap is bridged
    assert abs(g._last_t - now) < 1

    loader = MagicMock()
    from unittest.mock import AsyncMock
    async def load_ret():
        return {"total_kwh": 100.0, "last_t": now - 3600.0}
    loader.async_load = AsyncMock(return_value={"total_kwh": 100.0, "last_t": now - 3600.0})
    g._store = loader
    asyncio.run(g.async_load())
    assert g._last_t is None           # long gap dropped by the loader
    assert g.total_kwh == 100.0
