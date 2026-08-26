"""Condensing pull-down: lower flow when return water is above dew point."""

import pytest

from custom_components.home_climate_control.condense import (
    RETURN_TARGET_C,
    condense_pull,
)


def test_no_pull_when_return_cool():
    flow, pull = condense_pull(55.0, 48.0, min_flow=25.0)
    assert pull == 0.0
    assert flow == 55.0


def test_pull_when_return_hot():
    # return 58 → 4 °C over target → pull 4 °C
    flow, pull = condense_pull(60.0, 58.0, min_flow=25.0)
    assert pull == pytest.approx(58.0 - RETURN_TARGET_C)
    assert flow == pytest.approx(60.0 - pull)


def test_respects_min_flow():
    flow, pull = condense_pull(28.0, 70.0, min_flow=25.0, max_pull=20.0)
    assert flow == 25.0
    assert pull == pytest.approx(3.0)


def test_skips_when_rooms_cold():
    flow, pull = condense_pull(
        60.0, 60.0, min_flow=25.0, worst_deficit_c=2.5
    )
    assert pull == 0.0
    assert flow == 60.0


def test_none_return_passthrough():
    flow, pull = condense_pull(50.0, None, min_flow=25.0)
    assert flow == 50.0 and pull == 0.0


@pytest.mark.asyncio
async def test_controller_applies_condense_pull():
    from unittest.mock import MagicMock

    from custom_components.home_climate_control.central import CentralController
    from tests.test_controller import FakeBackend, FakeZone

    class RetBackend(FakeBackend):
        @property
        def return_temp(self):
            return 60.0  # hot return

    hass = MagicMock()
    be = RetBackend()
    be._outdoor = 5.0
    ctrl = CentralController(
        hass, be, curve_coeff=1.0, design_outdoor=-10,
        min_flow=25, max_flow=75,
    )
    # Small deficit so condense is allowed
    z = FakeZone("R", wants=True, demand=0.5, setpoint=20.0, pid_extra=0.0)
    z._current_temp = 19.5
    ctrl.zones = [z]
    await ctrl.async_control_step()
    assert ctrl._condense_active is True
    assert ctrl._condense_pull_c > 0
    assert be.flow is not None
    assert be.flow < 60.0  # pulled below unconstrained curve+pid
