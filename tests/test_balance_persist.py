"""BalanceMonitor state round-trip (learned info survives updates)."""

from custom_components.home_climate_control.balancing import BalanceMonitor


def test_round_trip():
    m = BalanceMonitor()
    for _ in range(30):
        m.sample(8.0, False)
    st = m.to_state()
    n = BalanceMonitor()
    n.from_state(st)
    rep = n.report()
    assert rep["state"] == "oversupplied"
    assert rep["avg_open_pct"] == 8.0


def test_from_state_bad_payload_never_crashes():
    m = BalanceMonitor()
    m.sample(10, False)
    # malformed payloads must not crash and must not resurrect data
    m.from_state(None)
    m.from_state({"hist": "junk"})
    m.from_state({"hist": [["x", 1]]})
    assert m.report()["samples"] == 0


def test_window_restore():
    m = BalanceMonitor(window=60)
    st = {"version": 1, "window": 120, "hist": [[5.0, True]] * 3}
    m.from_state(st)
    assert m._hist.maxlen == 120
