"""Manual temperature vs preset: override + auto-align semantics."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from custom_components.home_climate_control.zone import ZoneClimateEntity


def _manual_zone(preset="eco", preset_temps=None):
    z = object.__new__(ZoneClimateEntity)
    z._trv_entity = "climate.office_trv"
    z.heater_control = "smart"
    z._target_temp = 19.0
    z._preset = preset
    z._preset_source = "schedule"
    z._attr_min_temp = 5.0
    z._attr_max_temp = 30.0
    z._zone_name = lambda: "Office"
    z._valve_pct = None
    z.effective_setpoint = lambda: z._target_temp
    z._trv_state = lambda: None
    z._safe_write_ha_state = lambda: None
    coord = MagicMock()
    coord.debug_log = MagicMock()
    coord.preset_temps = preset_temps or {
        "comfort": 21.0, "eco": 19.0, "away": 15.0, "boost": 23.0,
    }
    calib = MagicMock()
    calib.active.return_value = False
    coord.calibration = calib
    z.coordinator = coord
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    z.hass = hass
    z._hass = hass
    return z, hass, coord


def test_manual_temp_overrides_active_preset():
    """A manual temp distinct from every preset drops the preset."""
    z, hass, _ = _manual_zone(preset="eco")
    asyncio.run(z.async_set_temperature(temperature=22.5))
    assert z._preset == "none"
    assert z._preset_source == "user"
    assert z._target_temp == 22.5
    assert hass.services.async_call.await_count == 1


def test_manual_temp_equal_to_preset_selects_it():
    """A manual temp equal to a preset's temp auto-selects that preset."""
    z, hass, _ = _manual_zone(preset="eco")
    asyncio.run(z.async_set_temperature(temperature=21.0))  # == comfort
    assert z._preset == "comfort"
    assert z._preset_source == "user"
    assert z._target_temp == 21.0
    assert hass.services.async_call.await_count == 1


def test_manual_temp_equal_to_active_preset_keeps_it():
    """Setting the active preset's own temp keeps that preset selected."""
    z, _, _ = _manual_zone(preset="eco")
    asyncio.run(z.async_set_temperature(temperature=19.0))
    assert z._preset == "eco"
    assert z._preset_source == "user"


def test_calibration_write_bypasses_align():
    """The calibrator's boosted write must not touch preset/source."""
    z, hass, coord = _manual_zone(preset="eco")
    coord.calibration.active.return_value = True
    coord.calibration.active_zone = "Office"
    asyncio.run(z.async_set_temperature(temperature=21.0))
    assert z._preset == "eco"                      # untouched
    assert z._preset_source == "schedule"          # untouched
    assert z._target_temp == 21.0                  # boost applied
    assert hass.services.async_call.await_count == 1


def test_manual_temp_outside_range_is_clamped():
    z, _, _ = _manual_zone(preset="none")
    asyncio.run(z.async_set_temperature(temperature=99.0))
    assert z._target_temp == 30.0


def test_rename_learning_migrates_learner_model():
    """Rename must carry the AI model like every other learned store."""
    from unittest.mock import MagicMock
    from custom_components.home_climate_control.central import (
        CentralController,
    )
    ctrl = object.__new__(CentralController)
    ctrl.learner = MagicMock()
    ctrl.learner.rename_room = MagicMock()
    ctrl.setbacks = MagicMock();
    ctrl.setbacks.rooms = {"Old": {"warm_ema": 1.0}}
    ctrl.setbacks._persist = lambda: None
    ctrl.deadtime = MagicMock()
    ctrl.deadtime.estimates = {}
    ctrl.deadtime._persist = lambda: None
    ctrl.insulation = MagicMock()
    ctrl.insulation.rooms = {}
    ctrl.insulation._persist = lambda: None
    ctrl.health = MagicMock()
    ctrl.health.rooms = {"Old": "ok"}
    ctrl.calibration = MagicMock()
    ctrl.calibration.active_zone = None
    CentralController.rename_zone_learning(ctrl, "Old", "New")
    assert ctrl.setbacks.rooms.get("Old") is None
    renamed = ctrl.learner.rename_room.call_args_list
    assert any(c.args == ("Old", "New") for c in renamed), renamed
