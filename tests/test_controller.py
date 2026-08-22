"""Tests for boiler backend + central controller with mocks (no real HA)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from home_climate_control.boiler.base import BoilerBackend
from home_climate_control.boiler.otgw_mqtt import OtgwMqttBackend
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
async def test_otgw_topics():
    hass = MagicMock()
    be = OtgwMqttBackend(hass, prefix="OTGW", node_id="otgw-ABC", min_flow=25, max_flow=75)
    assert be._value_topic("outside_temp") == "OTGW/outsidetemperature"
    assert be._value_topic("flow_temp") == "OTGW/boilertemperature"
    assert be._cmd_topic("ctrlsetpt") == "OTGW/set/otgw-ABC/ctrlsetpt"


@pytest.mark.asyncio
async def test_otgw_set_flow_clamps_and_publishes():
    import homeassistant.components.mqtt as mqtt

    mqtt.async_publish = AsyncMock()
    hass = MagicMock()
    be = OtgwMqttBackend(hass, prefix="OTGW", node_id="node1", min_flow=30, max_flow=60)
    await be.async_set_flow_setpoint(99.0)
    assert be._commanded_setpoint == 60.0
    mqtt.async_publish.assert_awaited()
    args = mqtt.async_publish.await_args
    assert args.args[1] == "OTGW/set/node1/ctrlsetpt"
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
