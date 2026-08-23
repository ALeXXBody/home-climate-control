"""Tests for boiler backend + central controller with mocks (no real HA)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from home_climate_control.boiler.base import BoilerBackend
from home_climate_control.boiler.hcs_mqtt import HcsMqttBackend
from home_climate_control.central import CentralController
from home_climate_control.heating_curve import flow_for_outdoor


class FakeBackend(BoilerBackend):
    def __init__(self) -> None:
        self.ch_enabled = False
        self.flow = None
        self.max_mod = None
        self._outdoor = 5.0
        self.started = False

    async def async_start(self) -> None:
        self.started = True

    async def async_stop(self) -> None:
        self.started = False

    async def async_set_ch_enabled(self, enabled: bool) -> None:
        self.ch_enabled = enabled

    async def async_set_flow_setpoint(self, temp: float) -> None:
        self.flow = temp

    async def async_set_max_modulation(self, percent: float) -> None:
        self.max_mod = percent

    @property
    def outdoor_temp(self):
        return self._outdoor

    @property
    def flow_temp(self):
        return self.flow

    @property
    def return_temp(self):
        return None

    @property
    def modulation_level(self):
        return None

    @property
    def flame_on(self):
        return self.ch_enabled

    @property
    def ch_active(self):
        return self.ch_enabled


class FakeZone:
    def __init__(
        self,
        name: str,
        *,
        wants: bool = True,
        paused: bool = False,
        setpoint: float = 20.0,
        pid_extra: float = 2.0,
        demand: float = 0.5,
    ) -> None:
        self.name = name
        self._wants = wants
        self._paused = paused
        self._setpoint = setpoint
        self._pid_extra = pid_extra
        self._demand = demand

    def wants_heat(self) -> bool:
        return self._wants

    def paused(self) -> bool:
        return self._paused

    def effective_setpoint(self) -> float:
        return self._setpoint

    def pid_flow_contribution(self) -> float:
        return self._pid_extra

    def demand_level(self) -> float:
        return self._demand


@pytest.mark.asyncio
async def test_hcs_topics():
    hass = MagicMock()
    be = HcsMqttBackend(hass, prefix="hcs", node_id="hcs-ABC", min_flow=25, max_flow=75)
    assert be.base == "hcs/hcs-ABC"
    assert be._cmd_topic("flow_setpoint") == "hcs/hcs-ABC/set/flow_setpoint"


@pytest.mark.asyncio
async def test_otgw_set_flow_clamps_and_publishes():
    import homeassistant.components.mqtt as mqtt

    mqtt.async_publish = AsyncMock()
    hass = MagicMock()
    be = HcsMqttBackend(hass, prefix="hcs", node_id="node1", min_flow=30, max_flow=60)
    await be.async_set_flow_setpoint(99.0)
    assert be._commanded_setpoint == 60.0
    mqtt.async_publish.assert_awaited()
    args = mqtt.async_publish.await_args
    assert args.args[1] == "hcs/node1/set/flow_setpoint"
    assert args.args[2] == "60.0"


@pytest.mark.asyncio
async def test_central_turns_ch_off_when_no_demand():
    hass = MagicMock()
    backend = FakeBackend()
    ctrl = CentralController(
        hass, backend, curve_coeff=1.2, design_outdoor=-10, min_flow=25, max_flow=75
    )
    ctrl.zones = [FakeZone("living", wants=False)]
    await ctrl.async_control_step()
    assert backend.ch_enabled is False
    assert ctrl.flow_setpoint is None
    assert ctrl.total_demand == 0.0


@pytest.mark.asyncio
async def test_central_commands_flow_when_zone_demands():
    hass = MagicMock()
    backend = FakeBackend()
    backend._outdoor = 0.0
    ctrl = CentralController(
        hass, backend, curve_coeff=1.2, design_outdoor=-10, min_flow=25, max_flow=75
    )
    ctrl.zones = [FakeZone("living", wants=True, setpoint=20.0, pid_extra=3.0, demand=0.6)]
    await ctrl.async_control_step()
    assert backend.ch_enabled is True
    assert backend.flow is not None
    assert 25 <= backend.flow <= 75
    assert ctrl.flow_setpoint == backend.flow
    assert "living" in ctrl.active_zone_names
    assert ctrl.total_demand == pytest.approx(0.6)


@pytest.mark.asyncio
async def test_central_skips_paused_zones():
    hass = MagicMock()
    backend = FakeBackend()
    ctrl = CentralController(
        hass, backend, curve_coeff=1.0, design_outdoor=-10, min_flow=25, max_flow=75
    )
    ctrl.zones = [FakeZone("bath", wants=True, paused=True)]
    await ctrl.async_control_step()
    assert backend.ch_enabled is False


@pytest.mark.asyncio
async def test_central_uses_worst_zone_pid():
    hass = MagicMock()
    backend = FakeBackend()
    backend._outdoor = 5.0
    ctrl = CentralController(
        hass, backend, curve_coeff=1.0, design_outdoor=-10, min_flow=25, max_flow=75
    )
    ctrl.zones = [
        FakeZone("a", wants=True, setpoint=20.0, pid_extra=1.0, demand=0.3),
        FakeZone("b", wants=True, setpoint=20.0, pid_extra=8.0, demand=0.7),
    ]
    await ctrl.async_control_step()
    base = flow_for_outdoor(20.0, 5.0, 1.0, 25, 75, -10)
    assert backend.flow == pytest.approx(min(75, base + 8.0))


@pytest.mark.asyncio
async def test_demo_backend_heats_when_ch_on():
    from home_climate_control.boiler.demo import DemoBoilerBackend

    demo = DemoBoilerBackend(25, 75, outdoor=5.0, rooms={"Living Room": 18.0})
    await demo.async_start()
    await demo.async_set_ch_enabled(True)
    await demo.async_set_flow_setpoint(55.0)

    class Z:
        name = "Living Room"

        def wants_heat(self):
            return True

        def paused(self):
            return False

        def on_sensor_update(self, t, w):
            self.temp = t

    z = Z()
    demo._last_tick -= 120  # force a large dt
    demo.simulate_step([z])
    assert demo.flame_on is True
    assert demo.ch_active is True
    assert demo.modulation_level > 0
    assert demo.get_room_temp("Living Room") > 18.0
    assert demo.diagnostics()["demo"] is True


@pytest.mark.asyncio
async def test_demo_backend_idle_when_ch_off():
    from home_climate_control.boiler.demo import DemoBoilerBackend

    demo = DemoBoilerBackend(25, 75, outdoor=5.0, rooms={"Bedroom": 19.0})
    await demo.async_start()
    await demo.async_set_ch_enabled(False)
    demo._last_tick -= 60
    demo.simulate_step([])
    assert demo.flame_on is False
    assert demo.modulation_level == 0.0


@pytest.mark.asyncio
async def test_central_with_demo_backend_commands_flow():
    from home_climate_control.boiler.demo import DemoBoilerBackend

    hass = MagicMock()
    demo = DemoBoilerBackend(25, 75, outdoor=0.0, rooms={"Living Room": 17.0})
    ctrl = CentralController(
        hass, demo, curve_coeff=1.2, design_outdoor=-10, min_flow=25, max_flow=75
    )
    ctrl.register_zone(
        FakeZone("Living Room", wants=True, setpoint=21.0, pid_extra=2.0, demand=0.8)
    )
    await ctrl.async_control_step()
    assert demo.ch_active is True or demo._ch_enabled is True
    assert ctrl.flow_setpoint is not None
    assert 25 <= ctrl.flow_setpoint <= 75


@pytest.mark.asyncio
async def test_build_backend_factory():
    """Regression: _build_backend must resolve for every backend type."""
    from unittest.mock import MagicMock

    from custom_components.home_climate_control import _build_backend
    from custom_components.home_climate_control.const import (
        BACKEND_DEMO,
        BACKEND_HCS,
        CONF_BACKEND,
        CONF_NODE_ID,
    )

    hass = MagicMock()
    entry = MagicMock()
    entry.data = {}
    entry.options = {}
    opts = {}

    # default (no backend key) -> native HCS backend, must not raise NameError
    be = _build_backend(hass, entry, opts)
    assert be is not None

    entry.data = {CONF_BACKEND: BACKEND_HCS, CONF_NODE_ID: "hcs-test"}
    be = _build_backend(hass, entry, opts)
    assert be is not None

    entry.data = {CONF_BACKEND: BACKEND_DEMO}
    be = _build_backend(hass, entry, opts)
    assert be is not None
