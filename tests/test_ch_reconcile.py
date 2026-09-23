"""Self-healing CH command delivery (reconcile belief vs boiler telemetry).

Regression for the OTA-reboot desync: the board lost the (non-retained)
CH-enable command, the controller kept believing CH was on and never
re-sent it — rooms demanded heat while the boiler stayed cold.
"""

from __future__ import annotations

import time as real_time
from unittest.mock import MagicMock

import pytest

from home_climate_control.central import CentralController
from tests.test_controller import FakeZone


class PlantBackend:
    """Commanded state + separate plant-reported CH-active telemetry."""

    def __init__(self) -> None:
        self.ch_enabled = False
        self.board_ch_active: bool | None = False   # plant ground truth
        self.commands: list[bool] = []
        self.flow = None
        self.flow_calls: list[tuple] = []
        self._outdoor = 5.0

    async def async_start(self) -> None: ...
    async def async_stop(self) -> None: ...

    async def async_set_ch_enabled(self, enabled: bool) -> None:
        self.ch_enabled = enabled
        self.commands.append(enabled)

    async def async_set_flow_setpoint(self, temp: float, *, force: bool = False) -> None:
        self.flow = temp
        self.flow_calls.append((temp, force))

    async def async_set_max_modulation(self, percent: float) -> None: ...

    @property
    def outdoor_temp(self):
        return self._outdoor

    @property
    def flow_temp(self):
        return 45.0

    @property
    def return_temp(self):
        return 30.0

    @property
    def modulation_level(self):
        return None

    @property
    def flame_on(self):
        return bool(self.flow)

    @property
    def ch_active(self):
        return self.board_ch_active


@pytest.fixture
def clock(monkeypatch):
    class Clock:
        t = 10_000.0

    monkeypatch.setattr(real_time, "monotonic", lambda: Clock.t)
    yield Clock


def _controller(plant):
    ctrl = CentralController(
        MagicMock(), plant, curve_coeff=1.2, design_outdoor=-10,
        min_flow=25, max_flow=75,
    )
    ctrl.zones = [FakeZone("living", wants=True, setpoint=20.0, demand=0.6)]
    return ctrl


@pytest.mark.asyncio
async def test_lost_ch_command_is_reasserted(clock):
    plant = PlantBackend()
    ctrl = CentralController(
        MagicMock(), plant, curve_coeff=1.2, design_outdoor=-10,
        min_flow=25, max_flow=75,
    )
    ctrl.zones = [FakeZone("living", wants=True, setpoint=20.0, demand=0.6)]

    await ctrl.async_control_step()
    assert plant.commands == [True]          # CH commanded on
    plant.flow = None

    # Board reboots and loses the command: plant reports ch_active=False.
    plant.board_ch_active = False
    plant.ch_enabled = False                 # the board's RAM state

    clock.t = 10_200.0                       # ~200 s after the command
    await ctrl.async_control_step()
    assert plant.commands == [True]          # one mismatch is not enough

    clock.t = 10_300.0                       # 300 s after, 2nd mismatch
    await ctrl.async_control_step()
    assert plant.commands == [True, True]    # ... but two heal it
    assert plant.ch_enabled is True


@pytest.mark.asyncio
async def test_periodic_heartbeat_while_ch_on(clock):
    plant = PlantBackend()
    ctrl = CentralController(
        MagicMock(), plant, curve_coeff=1.2, design_outdoor=-10,
        min_flow=25, max_flow=75,
    )
    ctrl.zones = [FakeZone("living", wants=True, setpoint=20.0, demand=0.6)]

    await ctrl.async_control_step()
    assert plant.commands == [True]

    # Aligned and inside one heartbeat window: no extra command.
    clock.t += 200.0
    await ctrl.async_control_step()
    assert plant.commands == [True]

    # Heartbeat window elapsed: the state is re-asserted (ON).
    clock.t += 150.0                         # 350 s > CH_HEARTBEAT_S
    await ctrl.async_control_step()
    assert plant.commands == [True, True]
    assert plant.ch_enabled is True


@pytest.mark.asyncio
async def test_stuck_ch_on_gets_turned_off(clock):
    plant = PlantBackend()
    plant.board_ch_active = True             # boiler burning at boot
    ctrl = CentralController(
        MagicMock(), plant, curve_coeff=1.2, design_outdoor=-10,
        min_flow=25, max_flow=75,
    )
    ctrl.zones = [FakeZone("living", wants=False)]

    await ctrl.async_control_step()          # believes off already
    assert plant.commands == []              # nothing commanded yet

    clock.t += 100.0                         # 2nd mismatched telemetry tick
    await ctrl.async_control_step()
    assert plant.commands == [False]         # ⇒ re-assert OFF
    assert plant.ch_enabled is False


@pytest.mark.asyncio
async def test_no_telemetry_never_fires_mismatch(clock):
    plant = PlantBackend()
    plant.board_ch_active = None             # no telemetry (or demo backend)
    ctrl = CentralController(
        MagicMock(), plant, curve_coeff=1.2, design_outdoor=-10,
        min_flow=25, max_flow=75,
    )
    ctrl.zones = [FakeZone("living", wants=True, setpoint=20.0, demand=0.6)]

    await ctrl.async_control_step()
    assert plant.commands == [True]
    for _ in range(5):
        clock.t += 100.0
        await ctrl.async_control_step()
        plant.board_ch_active = None
    # Only the 300 s heartbeats, never a mismatch storm.
    assert plant.commands == [True, True]


@pytest.mark.asyncio
async def test_heartbeat_reasserts_flow_setpoint_with_force(clock):
    plant = PlantBackend()
    ctrl = CentralController(
        MagicMock(), plant, curve_coeff=1.2, design_outdoor=-10,
        min_flow=25, max_flow=75,
    )
    ctrl.zones = [FakeZone("living", wants=True, setpoint=20.0, demand=0.6)]

    await ctrl.async_control_step()
    assert plant.commands == [True]
    assert plant.flow is not None
    assert plant.flow_calls[-1][1] is False       # normal publish, no force

    clock.t += 350.0                              # past CH_HEARTBEAT_S
    await ctrl.async_control_step()
    assert plant.commands == [True, True]
    # The heartbeat must also force the flow setpoint back through.
    assert any(f[1] is True for f in plant.flow_calls)
