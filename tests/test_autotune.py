"""Auto-tune curve coefficient: comfort-driven gas minimisation."""

from custom_components.home_climate_control.autotune import (
    DEADBAND_C,
    CurveAutoTuner,
)


class FakeStore:
    def __init__(self):
        self.saved = None

    async def async_load(self):
        return self.saved

    async def async_save(self, d):
        self.saved = d


def make_tuner(enabled=True, coeff=1.2):
    t = CurveAutoTuner(None, coeff, enabled=enabled)
    t._store = FakeStore()
    return t


def feed(tuner, err, n, dt_s=60.0, clock=[1000.0]):
    """Simulate n ticks (60 s apart) of constant mean error."""
    for _ in range(n):
        clock[0] += dt_s
        tuner.observe(err if err is not None else None, err is not None,
                      now=clock[0])


def test_no_change_inside_deadband():
    t = make_tuner()
    feed(t, 0.05, 60)
    assert t.step() is None
    assert "holding" in t.last_action or "ok" in t.last_action


def test_chronic_cold_raises_coefficient():
    t = make_tuner(coeff=1.2)
    feed(t, +0.8, 40)  # rooms 0.8C cold for ~40 min
    new = t.step(now=10_000.0)
    assert new is not None and new > 1.2
    # cooldown: immediate second step refused
    assert t.step(now=10_001.0) is None
    # persisted
    assert t._store.saved["coeff"] == new


def test_overshoot_lowers_coefficient():
    t = make_tuner(coeff=1.8)
    feed(t, -0.9, 40)  # rooms running hot = wasted gas
    new = t.step(now=20_000.0)
    assert new is not None and new < 1.8


def test_bounds_respected():
    t = make_tuner(coeff=3.0)
    t.coeff_max = 3.0
    feed(t, +5.0, 40)
    now = 30_000.0
    moved = False
    for _ in range(50):
        r = t.step(now=now)
        now += 4000.0
        if r is not None:
            moved = True
    assert t.coeff <= 3.0
    assert not moved or "limit" in t.last_action or t.coeff >= 2.9


def test_disabled_never_moves():
    t = make_tuner(enabled=False)
    feed(t, +2.0, 200)
    assert t.step() is None


def test_idle_signal_decays_not_accumulates():
    t = make_tuner()
    feed(t, +1.0, 30)
    for _ in range(30):  # heating stops (window open etc.)
        t.observe(None, False)
    assert abs(t._ema) < 0.6 * 1.0


def test_persistence_roundtrip():
    import asyncio

    t = make_tuner(coeff=1.5)
    feed(t, +1.0, 40)
    new = t.step(now=40_000.0)
    assert new is not None

    t2 = make_tuner(coeff=1.2)
    t2._store.saved = {"coeff": new, "adjustments": 1}
    asyncio.run(t2.async_load())
    assert t2.coeff == new


def test_controller_feeds_autotune_and_applies_learning():
    """Integration: demanding cold zone -> tuner raises controller coeff."""
    from unittest.mock import MagicMock

    from custom_components.home_climate_control.central import CentralController

    hass = MagicMock()
    backend = MagicMock()
    backend.outdoor_temp = -5.0
    backend.diagnostics.return_value = {}

    tuner = make_tuner(coeff=1.2)

    class Z:
        name = "living"
        _current_temp = 18.0

        def wants_heat(self):
            return True

        def paused(self):
            return False

        def effective_setpoint(self):
            return 21.0

        def demand_level(self):
            return 0.5

        def pid_flow_contribution(self):
            return 0.0

    c = CentralController(
        hass, backend, curve_coeff=1.2, design_outdoor=-10.0,
        min_flow=25.0, max_flow=75.0, autotune=tuner,
    )
    c.zones = [Z()]

    async def nope(*a, **k):
        return None

    backend.async_set_ch_enabled = nope
    backend.async_set_flow_setpoint = nope

    # Pre-warm the comfort-error EMA (real-time loop can't accumulate it).
    tuner._ema = 0.8
    tuner._last_sample_mono = 1.0
    import time as _t

    base = _t.monotonic()
    for i in range(5):
        c.autotune._next_eval_mono = 0.0
        c.autotune._cooldown_until_mono = 0.0
        import asyncio as aio

        aio.run(c.async_control_step())
        base += 1.0
        if c.curve_coeff > 1.2:
            break

    assert c.curve_coeff > 1.2
    diag = c.diagnostics()
    assert diag["autotune"]["enabled"] is True
    assert diag["curve_coeff"] == c.curve_coeff


def test_controller_without_autotune_unchanged():
    from unittest.mock import MagicMock

    from custom_components.home_climate_control.central import CentralController

    hass = MagicMock()
    backend = MagicMock()
    backend.outdoor_temp = -5.0
    backend.diagnostics.return_value = {}

    class Z:
        name = "r"
        _current_temp = 18.0

        def wants_heat(self):
            return True

        def paused(self):
            return False

        def effective_setpoint(self):
            return 21.0

        def demand_level(self):
            return 0.4

        def pid_flow_contribution(self):
            return 0.0

    c = CentralController(
        hass, backend, curve_coeff=1.2, design_outdoor=-10.0,
        min_flow=25.0, max_flow=75.0, autotune=None,
    )
    c.zones = [Z()]

    async def nope(*a, **k):
        return None

    backend.async_set_ch_enabled = nope
    backend.async_set_flow_setpoint = nope
    import asyncio as aio

    aio.run(c.async_control_step())
    assert c.curve_coeff == 1.2
    assert "autotune" not in c.diagnostics()
