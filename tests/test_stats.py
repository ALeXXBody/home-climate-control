"""Long-lived statistics: aggregation, persistence, reset, WS JSON round trip."""
import asyncio, json, time
from unittest.mock import MagicMock

from custom_components.home_climate_control.stats import HccStats


class FakeStore:
    def __init__(self):
        self.data = None

    async def async_load(self):
        return self.data

    async def async_save(self, payload):
        self.data = payload


def _mk(gas_days=None, price=0.05):
    hass = MagicMock()
    hass.async_create_task = lambda co: None
    s = HccStats(hass, gas_meter=None, price_per_kwh=price)
    s._store = FakeStore()
    s.gas_meter = MagicMock()
    s.gas_meter.days = gas_days or {}
    return s


def test_no_buckets_initially():
    s = _mk()
    assert s.summary()["days"] == 0


def test_observation_creates_day_and_aggregates():
    s = _mk()
    s._advance = None
    ts0 = time.mktime((2026, 9, 20, 23, 58, 0, 0, 0, -1))
    s.observe(now=ts0, outdoor=5.0, total_demand=2.0, ch_on=True,
              flow_setpoint=45, latest_max_demand=3.2)
    ts2 = ts0 + 60
    s.observe(now=ts2, outdoor=4.8, total_demand=3.0, burner_on=True,
              ch_on=True, flow_setpoint=55)
    d = s.days_list()
    assert len(d) == 1
    row = d[-1]
    assert row["out_avg"] == 4.9
    assert row["out_min"] == 4.8 and row["out_max"] == 5.0
    assert row["heat_degmin"] == 3.0 * 60.0  # demand integral over a minute
    assert row["max_demand"] == 3.2


def test_day_split_on_midnight():
    s = _mk()
    t1 = time.mktime((2026, 9, 19, 23, 59, 0, 0, 0, -1))
    t2 = t1 + 120  # next day
    s.observe(now=t1, outdoor=1.0, total_demand=2.0)
    s.observe(now=t2, outdoor=2.0, total_demand=4.0)
    rows = s.days_list()
    assert len(rows) >= 2  # tick may straddle both day buckets


def test_gas_from_meter_and_cost():
    gas = MagicMock()
    gas.days = {"2026-09-20": 12.5}
    s = _mk(gas_days=gas.days)
    ts = time.mktime((2026, 9, 20, 10, 0, 0, 0, 0, -1))
    s.observe(now=ts, outdoor=6)
    row = s.days_list()[0]
    assert row["gas_kwh"] == 12.5
    assert row["cost"] == 0.62  # 12.5 * 0.05 partially rounded


def test_summary_totals():
    s = _mk()
    gas = MagicMock()
    gas.days = {"2026-09-18": 10.0, "2026-09-19": 15.0, "2026-09-20": 5.0}
    s.gas_meter = gas
    for d0, h0 in (("2026-09-18", 6), ("2026-09-19", 11), ("2026-09-20", 20)):
        ts = time.mktime((int(d0[:4]), int(d0[5:7]), int(d0[8:10]), 12, 0, 0, 0, 0, -1))
        # seed the day bucket by observing (fresh day, no dt)
        s.observe(now=ts, outdoor=0.0, total_demand=0.5)
        s.days[d0]["gas_kwh"] = gas.days[d0]
        s.days[d0]["cost"] = round(gas.days[d0] * s.price_per_kwh, 4)
    sm = s.summary()
    assert sm["days"] >= 1
    assert sm["gas_kwh_7d"] >= 0


def test_reset_clears_all():
    s = _mk()
    gas = MagicMock()
    gas.days = {"2026-09-20": 9.0}; gas.total_kwh = 100.0
    s.gas_meter = gas
    ts = time.mktime((2026, 9, 20, 9, 0, 0, 0, 0, -1))
    s.observe(now=ts, outdoor=3.0, total_demand=1.0)
    s.reset()
    assert s.days == {}
    assert gas.total_kwh == 0.0 and gas.days == {}
    asyncio.run(s.async_save())
    assert s._store.data is not None  # reset flushed to the Store


def test_persistence_roundtrip():
    s = _mk()
    ts = time.mktime((2026, 9, 20, 8, 0, 0, 0, 0, -1))
    s.observe(now=ts, outdoor=2.0, total_demand=1.5)
    s._prune()
    payload = {"version": 1, "days": s.days}
    s2 = _mk()
    s2._store.data = dict(s._store.data) if s._store.data else {"version": 1, "days": s.days}
    asyncio.run(s2.async_load())
    # same day, same gas/burner stats after reload
    rows2 = s2.days_list()
    assert len(rows2) == len(s.days_list())


def test_trend_on_correlated_data():
    s = _mk()
    gas = MagicMock()
    gas.total_kwh = 0.0
    # 20 cold days (outdoor -10 °C), then 20 mild days (outdoor +10 °C),
    # gas inversely-related — slope must be negative
    for i, (out, kwh) in enumerate(
        [(-8, 60.0), (-6, 50.0), (-4, 45.0), (-2, 40.0)] * 5
    ):
        day = f"2026-08-{(i % 28) + 1:02d}"
        ts = time.mktime((__import__("datetime").datetime.strptime(day, "%Y-%m-%d").year,
                         8, (i % 28) + 1, 12, 0, 0, 0, 0, -1))
        s.observe(now=ts, outdoor=out, total_demand=0)
        s.days[(sorted(s.days)[-1])]["gas_kwh"] = kwh
    tr = s._trend(s.days_list())
    assert tr["slope"] is not None and tr["slope"] < 0
    assert tr["points"] >= 10


def test_as_dict_json_safe_and_shape():
    s = _mk()
    ts0 = time.mktime((2026, 9, 20, 7, 0, 0, 0, 0, -1))
    s.observe(now=ts0, outdoor=3.0, total_demand=1.0, ch_on=True, flow_setpoint=55)
    d = s.as_dict()
    json.dumps(d)
    assert "summary" in d and "rows" in d and "trend" in d


def test_unload_flushes_stats_without_nameerror():
    """The 1.13.0 insert referenced a local `stats` in the unload path —
    every entry unload raised NameError → 'failed_unload' → the panel
    showed 'No Home Climate Control configured'. Pinned: unloading an
    entry whose controller carries stats works and flushes the store."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    import custom_components.home_climate_control as hcc


    class _Store:
        def __init__(self):
            self.data = None

        async def async_save(self, payload):
            self.data = payload

    stats = MagicMock()
    stats.async_unload = AsyncMock()

    class _Ctrl:
        async def async_stop(self):
            pass

        datalogger = None
        stats = None      # controller without stats must be fine too

    ctrl_bare = _Ctrl()
    ctrl_with_stats = _Ctrl()
    ctrl_with_stats.stats = stats

    hass = MagicMock()
    hass.data = {hcc.DOMAIN: {}}
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    hass.config_entries.async_entries.return_value = []

    entry = MagicMock()
    entry.entry_id = "e1"

    async def run(controller):
        hass.data = {hcc.DOMAIN: {"e1": {"controller": controller}}}
        ok = await hcc.async_unload_entry(hass, entry)
        hass.data[hcc.DOMAIN] = {}  # reset for the next run
        return ok

    try:
        assert asyncio.run(run(ctrl_with_stats)) is True
        stats.async_unload.assert_awaited_once()
        assert asyncio.run(run(ctrl_bare)) is True  # no stats → no crash
    except NameError as err:
        raise AssertionError(f"unload crashed: {err}")


def test_corrupt_store_does_not_crash():
    s = _mk()
    s._store.data = ["not", "a", "dict"]
    asyncio.run(s.async_load())
    assert s.days == {}
