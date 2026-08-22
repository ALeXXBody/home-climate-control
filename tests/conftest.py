"""Shared fixtures: path + minimal Home Assistant stubs for unit tests."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

ROOT = Path(__file__).resolve().parents[1]
CC = ROOT / "custom_components"
if str(CC) not in sys.path:
    sys.path.insert(0, str(CC))


def _mod(name: str) -> types.ModuleType:
    if name in sys.modules:
        return sys.modules[name]
    m = types.ModuleType(name)
    m.__path__ = []  # mark as package
    sys.modules[name] = m
    return m


def install_ha_stubs() -> None:
    if getattr(install_ha_stubs, "_done", False):
        return

    ha = _mod("homeassistant")
    ha.__path__ = []

    # core
    core = _mod("homeassistant.core")
    core.HomeAssistant = type("HomeAssistant", (), {})
    core.callback = lambda f: f
    core.State = type("State", (), {})

    # config_entries
    ce = _mod("homeassistant.config_entries")
    ce.ConfigEntry = type("ConfigEntry", (), {})
    ce.ConfigFlow = type("ConfigFlow", (), {"async_get_options_flow": staticmethod(lambda e: None)})
    ce.OptionsFlow = type("OptionsFlow", (), {})
    ce.SOURCE_USER = "user"

    # const
    const = _mod("homeassistant.const")
    const.ATTR_TEMPERATURE = "temperature"
    const.CONF_NAME = "name"
    const.PRECISION_HALVES = 0.5
    const.UnitOfTemperature = types.SimpleNamespace(CELSIUS="°C")
    const.Platform = types.SimpleNamespace(CLIMATE="climate")

    # data_entry_flow
    def_ = _mod("homeassistant.data_entry_flow")
    def_.FlowResult = dict

    # components
    components = _mod("homeassistant.components")
    mqtt = _mod("homeassistant.components.mqtt")
    mqtt.async_subscribe = AsyncMock(return_value=lambda: None)
    mqtt.async_publish = AsyncMock()

    climate = _mod("homeassistant.components.climate")
    climate.ClimateEntity = type("ClimateEntity", (), {})
    climate.ClimateEntityFeature = types.SimpleNamespace(
        TARGET_TEMPERATURE=1, PRESET_MODE=2
    )
    climate.HVACMode = types.SimpleNamespace(HEAT="heat", OFF="off")
    climate.HVACAction = types.SimpleNamespace(HEATING="heating", IDLE="idle", OFF="off")

    # helpers
    helpers = _mod("homeassistant.helpers")
    event = _mod("homeassistant.helpers.event")
    event.async_track_time_interval = MagicMock(return_value=lambda: None)
    event.async_track_state_change_event = MagicMock(return_value=lambda: None)
    selector = _mod("homeassistant.helpers.selector")
    selector.EntitySelector = lambda *a, **k: str
    selector.EntitySelectorConfig = lambda **k: k
    entity_platform = _mod("homeassistant.helpers.entity_platform")
    entity_platform.AddEntitiesCallback = object
    aiohttp_client = _mod("homeassistant.helpers.aiohttp_client")
    aiohttp_client.async_get_clientsession = MagicMock()

    # voluptuous not needed if we don't import config_flow in unit tests

    ha.components = components
    ha.core = core
    ha.helpers = helpers
    ha.config_entries = ce
    ha.const = const
    components.mqtt = mqtt
    components.climate = climate
    helpers.event = event
    helpers.selector = selector
    helpers.aiohttp_client = aiohttp_client

    install_ha_stubs._done = True  # type: ignore[attr-defined]


install_ha_stubs()
