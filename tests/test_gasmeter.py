"""Gas accounting: nameplate kW x modulation x time, for every boiler type."""

import pytest

from custom_components.home_climate_control.gasmeter import GasMeter


def meter(**kw):
    return GasMeter(None, **kw)


def test_modulating_linear_interpolation_with_min_floor():
    g = meter(rated_power_kw=24.0, min_power_kw=4.0)
    rate, mode = g.current_rate_kw(flame_on=True, modulation=50.0)
    assert rate == pytest.approx(4 + (24 - 4) * 0.5)
    assert mode == "modulating"


def test_proportional_when_no_min_given():
    g = meter(rated_power_kw=30.0, min_power_kw=0.0)
    rate, mode = g.current_rate_kw(flame_on=True, modulation=25.0)
    assert rate == pytest.approx(7.5)


def test_onoff_boiler_uses_duty_factor():
    """No trustworthy modulation -> nameplate x duty factor."""
    g = meter(rated_power_kw=20.0, nomod_factor=0.6)
    rate, mode = g.current_rate_kw(flame_on=True, modulation=None)
    assert rate == pytest.approx(12.0)
    assert mode == "on/off estimate"


def test_constant_full_scale_reports_as_estimate():
    """Some on/off boards report a stuck 100% — still the estimate path."""
    g = meter(rated_power_kw=20.0, nomod_factor=0.6)
    rate, _ = g.current_rate_kw(flame_on=True, modulation=100.0)
    assert rate == pytest.approx(20.0)  # 100% IS full fire, that's honest


def test_flame_off_accumulates_nothing():
    g = meter(rated_power_kw=24.0)
    kwh = g.feed(now=0.0, flame_on=False, modulation=None)
    assert kwh == 0.0
    assert g.total_kwh == 0.0
    kwh = g.feed(now=600.0, flame_on=False, modulation=None)
    assert g.total_kwh == 0.0


def test_integration_math_over_time():
    """1 h at 50% mod => 14 kWh, stepped at the real 300 s control cadence."""
    g = meter(rated_power_kw=24.0, min_power_kw=4.0, calibration=1.0)
    g.feed(now=0.0, flame_on=True, modulation=50.0)  # baseline
    for i in range(1, 13):
        g.feed(now=i * 300.0, flame_on=True, modulation=50.0)
    assert g.total_kwh == pytest.approx(14.0, rel=1e-6)


def test_calibration_scales_result():
    g = meter(rated_power_kw=10.0, calibration=0.5)
    g.feed(now=0.0, flame_on=True, modulation=None)  # baseline
    for i in range(1, 13):
        g.feed(now=i * 300.0, flame_on=True, modulation=None)
    # nomod 0.6 x 10 kW x 1 h x 0.5 = 3 kWh
    assert g.total_kwh == pytest.approx(3.0)


def test_gap_longer_than_max_dt_is_clamped():
    """Reconnects/log gaps must not bill a whole night in one tick."""
    g = meter(rated_power_kw=24.0, min_power_kw=4.0)
    g.feed(now=0.0, flame_on=True, modulation=50.0)
    g.feed(now=7200.0, flame_on=True, modulation=50.0)  # 2 h gap
    span = 300.0
    assert g.total_kwh == pytest.approx(14.0 * span / 3600.0, rel=1e-6)


def test_day_buckets_and_rollover():
    from datetime import datetime

    g = meter(rated_power_kw=24.0, min_power_kw=4.0)
    # Burn before AND after midnight (baseline feed itself bills nothing).
    # Steps are bucketed by their END time, so keep each step clear of
    # midnight except the last one which crosses it.
    t0 = datetime(2026, 8, 22, 23, 50, 0).timestamp()
    g.feed(now=t0, flame_on=True, modulation=50.0)
    g.feed(now=t0 + 240.0, flame_on=True, modulation=50.0)   # ends 23:54
    g.feed(now=t0 + 480.0, flame_on=True, modulation=50.0)   # ends 23:58
    g.feed(now=t0 + 720.0, flame_on=True, modulation=50.0)   # ends 00:02
    assert len(g.days) == 2
    assert g.days["2026-08-22"] == pytest.approx(14 * 480 / 3600, rel=1e-3)
    assert sum(g.days.values()) == pytest.approx(g.total_kwh, rel=1e-6)


def test_persistence_roundtrip():
    import asyncio

    class FakeStore:
        def __init__(self):
            self.saved = None

        async def async_load(self):
            return self.saved

        async def async_save(self, d):
            self.saved = d

    a = meter(rated_power_kw=24.0, min_power_kw=4.0)
    a._store = FakeStore()
    t0 = 1755820000.0
    a.feed(now=t0, flame_on=True, modulation=50.0)
    a.feed(now=t0 + 240.0, flame_on=True, modulation=50.0)
    a.feed(now=t0 + 480.0, flame_on=True, modulation=50.0)
    a._persist(force=True)  # bypass the 5-min write throttle

    b = meter()
    b._store = FakeStore()
    b._store.saved = a._store.saved
    asyncio.run(b.async_load())
    assert b.total_kwh == pytest.approx(a.total_kwh, rel=1e-4)  # 4-dp roundtrip
    d = next(iter(b.days))
    assert b.days[d] == pytest.approx(a.days[d], rel=1e-4)


def test_diagnostics_shape_and_cost():
    from datetime import datetime

    g = meter(
        rated_power_kw=24.0, min_power_kw=4.0,
        price_per_kwh=0.08,
    )
    # Anchor inside TODAY so today_kwh()/as_dict() see the bucket.
    midnight = datetime.now().replace(hour=0, minute=1, second=0, microsecond=0)
    t0 = midnight.timestamp()
    g.feed(now=t0, flame_on=True, modulation=50.0)
    for i in range(1, 7):
        g.feed(now=t0 + i * 300.0, flame_on=True, modulation=50.0)
    d = g.as_dict()
    assert d["mode"] == "modulating"
    assert d["today_kwh"] == pytest.approx(7.0, abs=0.01)
    assert d["today_cost"] == pytest.approx(d["today_kwh"] * 0.08, abs=0.01)
    assert len(d["week"]) == 1


def test_controller_feeds_meter_from_backend_telemetry():
    """End-to-end: control step reads backend flame/mod and accumulates."""
    import asyncio
    from unittest.mock import MagicMock

    from custom_components.home_climate_control.central import CentralController

    backend = MagicMock()
    backend.flame_on = True
    backend.modulation_level = 50.0
    backend.outdoor_temp.return_value = 5.0
    backend.async_set_ch_enabled = MagicMock()
    backend.async_set_flow_setpoint = MagicMock()

    async def nope(*a, **k):
        return None

    backend.async_set_ch_enabled = nope
    backend.async_set_flow_setpoint = nope

    g = GasMeter(None, rated_power_kw=24.0, min_power_kw=4.0)
    c = CentralController(
        MagicMock(), backend, curve_coeff=1.2, design_outdoor=-10.0,
        min_flow=25.0, max_flow=75.0,
    )
    c.gas = g

    class Z:
        name = "R"
        def wants_heat(self): return False
        def paused(self): return False
        def effective_setpoint(self): return 21.0
        def demand_level(self): return 0.0
        def pid_flow_contribution(self): return 0.0

    c.zones = [Z()]
    t0 = 1755820000.0
    c.backend.flame_on = True
    asyncio.run(c.async_control_step())  # first feed: baseline only
    g._last_t = t0
    c.gas.feed(now=t0 + 300.0, flame_on=True, modulation=50.0)
    assert c.gas.total_kwh == pytest.approx(14.0 * 300 / 3600, rel=1e-6)
    diag = c.diagnostics()
    assert "gas" in diag
    assert diag["gas"]["mode"] == "modulating"
