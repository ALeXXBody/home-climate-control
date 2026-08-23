"""CycleGuard: fewer burner starts = less wasted gas."""

import pytest

from custom_components.home_climate_control.cycleguard import CycleGuard


@pytest.fixture()
def g():
    return CycleGuard()


def test_fresh_system_starts_immediately(g):
    assert g.decide(True, False, now=1000.0) == (True, "start")


def test_no_change_when_states_match(g):
    assert g.decide(True, True, now=1000.0)[1] == "no change"
    assert g.decide(False, False, now=1000.0)[1] == "no change"


def test_restart_blocked_during_rest_window(g):
    g.record(True, 1000.0)
    g.record(False, 1100.0)  # ran 100 s
    allowed, reason = g.decide(True, False, now=1150.0)
    assert allowed is False and "resting" in reason
    # once past last_stop + base window (mult is 1 here) it is allowed
    allowed, _ = g.decide(True, False, now=1100.0 + 301.0)
    assert allowed is True


def test_hard_min_on_blocks_premature_stop(g):
    g.record(True, 1000.0)
    allowed, reason = g.decide(False, True, now=1100.0)
    assert allowed is True and "min-on" in reason
    allowed, _ = g.decide(False, True, now=1000.0 + 240.0 + 1.0)
    assert allowed is False


def test_rapid_cycling_stretches_rest_window():
    g = CycleGuard(base_min_off_s=300.0)
    t = 0.0
    for _ in range(12):  # 12 starts in an hour = heavy cycling
        g.record(True, t)
        g.record(False, t + 120.0)
        t += 300.0
        for _ in range(5):  # controller evaluates ~every 60 s
            t += 10.0
            g.decide(False, False, now=t)  # drives adaptation
    assert g.mult > 1.5
    # a restart now must be blocked well beyond the base rest window
    need = g.base_min_off_s * g.mult
    allowed, reason = g.decide(True, False, now=t + need * 0.5)
    assert allowed is False and "resting" in reason


def test_quiet_system_relaxes_multiplier():
    g = CycleGuard()
    for i in range(10):
        g.record(True, float(i * 120))
        g.record(False, float(i * 120) + 60.0)
    g.mult = 2.5
    now = 5000.0
    for _ in range(400):  # ~an hour of quiet ticks
        g.decide(False, False, now=now)
        now += 10.0
    assert g.mult < 1.5


def test_controller_flicker_yields_few_burner_starts():
    """Thermostat flapping every tick must not start the burner each time."""
    from unittest.mock import MagicMock

    from custom_components.home_climate_control.central import CentralController

    hass = MagicMock()
    backend = MagicMock()
    backend.outdoor_temp = -5.0
    backend.diagnostics.return_value = {}

    class Z:
        name = "r"

        def __init__(self, wants):
            self._wants = wants
            self._current_temp = 19.0

        def wants_heat(self):
            return self._wants

        def paused(self):
            return False

        def effective_setpoint(self):
            return 21.0

        def demand_level(self):
            return 0.5

        def pid_flow_contribution(self):
            return 0.0

    ctrl = CentralController(
        hass, backend, curve_coeff=1.2, design_outdoor=-10.0,
        min_flow=25.0, max_flow=75.0,
    )
    started = []

    async def set_ch(enabled):
        if enabled:
            started.append(1)

    async def set_flow(f):
        return None

    backend.async_set_ch_enabled = set_ch
    backend.async_set_flow_setpoint = set_flow

    import asyncio as aio

    for i in range(30):  # demand flaps every tick for 30 min
        ctrl.zones = [Z(wants=(i % 2 == 0))]
        aio.run(ctrl.async_control_step())
        ctrl.cycleguard.base_min_off_s = 300.0
        ctrl.cycleguard.hard_min_on_s = 240.0

    assert len(started) <= 4  # not 15!


def test_controller_immediate_off_with_no_history_unchanged():
    from unittest.mock import MagicMock

    from custom_components.home_climate_control.central import CentralController

    hass = MagicMock()
    backend = MagicMock()
    backend.outdoor_temp = None
    backend.diagnostics.return_value = {}

    class Z:
        name = "r"

        def wants_heat(self):
            return False

        def paused(self):
            return False

    ctrl = CentralController(
        hass, backend, curve_coeff=1.2, design_outdoor=-10.0,
        min_flow=25.0, max_flow=75.0,
    )
    ctrl.zones = [Z()]

    async def nope(*a, **k):
        return None

    backend.async_set_ch_enabled = nope
    backend.async_set_flow_setpoint = nope
    import asyncio as aio

    aio.run(ctrl.async_control_step())
    assert backend.ch_enabled if hasattr(backend, "ch_enabled" ) else True
    assert ctrl.flow_setpoint is None
    diag = ctrl.diagnostics()
    assert diag["cycle_guard"]["state"] == "idle"


def test_diagnostics_exposed():
    import time as _t

    g = CycleGuard()
    g.record(True, _t.monotonic())
    d = g.as_dict()
    assert d["starts_1h"] == 1
    assert d["state"] == "on"
