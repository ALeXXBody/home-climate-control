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
    ce = _mod("homeassistant.config_entries")
    class _ConfigFlow:
        def __init_subclass__(cls, domain=None, **kw): 
            cls.DOMAIN = domain
            super().__init_subclass__(**kw)
        def __init__(self): 
            self.context = {}
        async def async_set_unique_id(self, uid): pass
        def _abort_if_unique_id_configured(self): pass
        async def async_show_form(self, **kw): return {"type": "form", **kw}
        async def async_create_entry(self, **kw): return {"type": "create_entry", **kw}
        async def async_abort(self, **kw): return {"type": "abort"}
    ce.ConfigFlow = _ConfigFlow
    ce.FlowResult = dict
    ce.SOURCE_USER = "user"
    ha.config_entries = ce
    entity_platform = _mod("homeassistant.helpers.entity_platform")
    entity_platform.AddEntitiesCallback = object
    aiohttp_client = _mod("homeassistant.helpers.aiohttp_client")
    aiohttp_client.async_get_clientsession = MagicMock()

    # components submodules used by the integration
    comp = _mod("homeassistant.components")
    comp_sensor = _mod("homeassistant.components.sensor")
    class _SensorDeviceClass:
        temperature = "temperature"
        humidity = "humidity"
    comp_sensor.SensorDeviceClass = _SensorDeviceClass
    comp_sensor.SensorEntity = object
    comp.persistent_notification = _mod(
        "homeassistant.components.persistent_notification")
    comp.persistent_notification.async_create = MagicMock()
    comp.frontend = _mod("homeassistant.components.frontend")
    comp.frontend.async_register_built_in_panel = MagicMock()
    ha.components = comp
    comp.sensor = comp_sensor
    comp.persistent_notification = comp.persistent_notification
    comp.frontend = comp.frontend
    comp_panel_custom = _mod("homeassistant.components.panel_custom")
    comp_panel_custom.async_register_panel = MagicMock()
    comp.panel_custom = comp_panel_custom

    wsapi = _mod("homeassistant.components.websocket_api")
    wsapi.websocket_command = lambda schema: (lambda fn: fn)
    wsapi.async_response = lambda fn: fn
    wsapi.register_command = MagicMock()
    class _ActiveConnection:  # noqa: D401
        pass
    wsapi.ActiveConnection = _ActiveConnection
    ha.websocket_api = wsapi
    comp.websocket_api = wsapi

    comp_http = _mod("homeassistant.components.http")
    class _StaticPathConfig:
        def __init__(self, url_path, path, cache_headers=True):
            self.url_path = url_path; self.path = path; self.cache_headers = cache_headers
    comp_http.StaticPathConfig = _StaticPathConfig
    ha.http_view = comp_http
    comp.http = comp_http

    comp_update = _mod("homeassistant.components.update")
    class _UpdateEntityFeature:
        INSTALL = 1
        RELEASE_NOTES = 2
        PROGRESS = 4
    class _UpdateDeviceClass:
        FIRMWARE = "firmware"
    comp_update.UpdateEntityFeature = _UpdateEntityFeature
    comp_update.UpdateDeviceClass = _UpdateDeviceClass
    comp_update.UpdateEntity = object
    ha.components.update = comp_update
    comp.update = comp_update

    dr = _mod("homeassistant.helpers.device_registry")
    class _DeviceInfo(dict):
        def __init__(self, **kw): super().__init__(**kw)
    dr.DeviceInfo = _DeviceInfo
    helpers.device_registry = dr

    net_helper = _mod("homeassistant.helpers.network")
    net_helper.get_url = lambda hass, prefer_internal=False: (
        "http://192.168.50.20:8123")
    helpers.network = net_helper
    storage = _mod("homeassistant.helpers.storage")
    class _Store:
        def __init__(self, *a, **k): pass
        async def async_load(self): return {}
        async def async_save(self, d): pass
    storage.Store = _Store

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
    helpers.storage = storage

    install_ha_stubs._done = True  # type: ignore[attr-defined]


install_ha_stubs()
