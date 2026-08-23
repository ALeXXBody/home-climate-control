"""Audit regression suite — locks in the bugs found 2026-08-23."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock


def test_discovery_async_init_passes_data_not_context_only():
    from custom_components.home_climate_control.firmware_manager import (
        FirmwareManager,
    )

    hass = MagicMock()
    hass.config_entries.async_entries.return_value = []
    hass.async_create_task = lambda c: (c.close() if hasattr(c, "close") else None)
    mgr = FirmwareManager(hass)
    msg = MagicMock()
    msg.topic = "hcs/discovery/hcs-x"
    msg.payload = json.dumps(
        {"node_id": "hcs-x", "board": "d1_mini", "version": "1.0.2"}
    )
    mgr._on_discovery(msg)
    kwargs = hass.config_entries.flow.async_init.call_args.kwargs
    assert kwargs.get("data") == {"node_id": "hcs-x"}
    assert kwargs.get("context", {}).get("source") == "discovery"


def test_build_backend_stores_object_and_unknown_raises():
    from custom_components.home_climate_control import _build_backend
    from custom_components.home_climate_control.boiler.demo import DemoBoilerBackend
    from custom_components.home_climate_control.const import (
        BACKEND_DEMO,
        CONF_BACKEND,
        CONF_ZONES,
    )

    entry = MagicMock()
    entry.data = {CONF_BACKEND: BACKEND_DEMO, "demo_outdoor": 5.0}
    opts = {
        CONF_ZONES: [{"name": "Living", "demo_start_temp": 18.0}],
        "min_flow_temp": 25,
        "max_flow_temp": 75,
    }
    backend = _build_backend(MagicMock(), entry, opts)
    assert isinstance(backend, DemoBoilerBackend)

    entry2 = MagicMock()
    entry2.data = {CONF_BACKEND: "garbage"}
    try:
        _build_backend(MagicMock(), entry2, opts)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_get_boiler_info_skips_non_entry_keys():
    from custom_components.home_climate_control import boiler_info as bi_mod
    from custom_components.home_climate_control.const import DOMAIN

    hass = MagicMock()
    info = MagicMock()
    bi_mod._ACTIVE = {"entry-real": info}
    hass.data = {
        DOMAIN: {
            "firmware_manager": object(),
            "entry-real": {"controller": object()},
        }
    }
    assert bi_mod.get_boiler_info(hass) is info
    bi_mod._ACTIVE = {}


def test_hcs_backend_ping_uses_global_topic():
    """Backend must ping hcs/discovery/ping (firmware subscription), not per-node."""
    from custom_components.home_climate_control.boiler.hcs_mqtt import HcsMqttBackend

    published = []

    async def fake_pub(hass, topic, payload, *a, **k):
        published.append(topic)

    async def fake_sub(hass, topic, cb, qos=0):
        return lambda: None

    import custom_components.home_climate_control.boiler.hcs_mqtt as mod

    orig_pub, orig_sub = mod.mqtt.async_publish, mod.mqtt.async_subscribe
    mod.mqtt.async_publish = fake_pub
    mod.mqtt.async_subscribe = fake_sub
    try:
        backend = HcsMqttBackend(MagicMock(), "hcs-node1", 25, 75)
        asyncio.run(backend.async_start())
    finally:
        mod.mqtt.async_publish = orig_pub
        mod.mqtt.async_subscribe = orig_sub
    assert "hcs/discovery/ping" in published
    assert not any(t.endswith("ping_discovery") for t in published)


def test_sensor_topic_scoped_to_node():
    from custom_components.home_climate_control.sensor import _topic_for_node

    assert _topic_for_node("hcs-abc", "failsafe") == "hcs/hcs-abc/failsafe"
    assert _topic_for_node("", "boiler_diag") == "hcs/+/boiler_diag"


def test_room_uses_trv_temp_when_no_external_sensor():
    """Room temp falls back to TRV current_temperature."""
    from unittest.mock import MagicMock
    from custom_components.home_climate_control.zone import ZoneClimateEntity

    hass = MagicMock()
    trv_state = MagicMock()
    trv_state.state = "heat"
    trv_state.attributes = {
        "current_temperature": 19.5,
        "temperature": 21.0,
        "hvac_action": "heating",
    }
    hass.states.get.return_value = trv_state

    coord = MagicMock()
    coord.curve_coeff = 1.2
    coord.flow_setpoint = 45.0
    entry = MagicMock()
    entry.entry_id = "e1"
    room = ZoneClimateEntity(
        hass,
        coord,
        entry,
        {
            "name": "Living",
            "trv_climates": ["climate.living_trv"],
            "temp_sensor": None,
            "window_sensors": ["binary_sensor.living_window"],
        },
    )
    room.async_write_ha_state = MagicMock()
    room._refresh_temp_from_trv()
    assert room.current_temperature == 19.5
    assert room.trv_entity == "climate.living_trv"
    assert room.window_sensor_entities == ["binary_sensor.living_window"]
    assert room.wants_heat() is False  # hvac off by default
    room._hvac_mode = room._hvac_mode.__class__("heat") if False else __import__(
        "homeassistant.components.climate", fromlist=["HVACMode"]
    ).HVACMode.HEAT
    assert room.wants_heat() is True
    room.on_sensor_update(None, True)  # window open
    assert room.paused() is True
    assert room.wants_heat() is False


def test_room_config_requires_trv():
    import asyncio
    from custom_components.home_climate_control.config_flow import (
        HomeClimateControlConfigFlow,
    )

    flow = HomeClimateControlConfigFlow()
    flow.context = {}
    flow._data = {
        "backend": "hcs",
        "node_id": "hcs-x",
        "name": "HCC",
        "min_flow_temp": 25,
        "max_flow_temp": 75,
        "curve_coeff": 1.2,
    }
    res = asyncio.run(
        flow.async_step_zone(
            {
                "name": "Living",
                "trv_climates": None,
                "temp_sensor": "sensor.living_t",
            }
        )
    )
    assert res["type"] == "form"
    assert res.get("errors", {}).get("base") == "trv_required"


def test_update_checker_install_cooldown_suppresses_available():
    """During post-Install quiet period, do not re-mark devices outdated."""
    import asyncio
    import time
    from unittest.mock import MagicMock

    from custom_components.home_climate_control.update_checker import UpdateChecker

    hass = MagicMock()
    uc = UpdateChecker(hass)
    uc.info = {
        "available": True,
        "latest_version": "1.0.8",
        "latest_tag": "v1.0.8",
        "outdated_devices": [
            {"node_id": "hcs-x", "version": "1.0.2", "board": "d1_mini"}
        ],
    }
    uc._notified_tag = "v1.0.8"
    uc.mark_install_started()
    assert uc._in_install_cooldown() is True
    assert uc.info["available"] is False
    assert uc.info["outdated_devices"] == []

    uc._last_fetch = time.monotonic()  # within MIN interval
    out = asyncio.run(uc.async_check(force=False))
    assert out["available"] is False
    assert out.get("installing") is True


def test_update_entity_no_progress_feature_and_stable_latest():
    from unittest.mock import MagicMock
    from homeassistant.components.update import UpdateEntityFeature
    from custom_components.home_climate_control.update import HcsFirmwareUpdateEntity

    hass = MagicMock()
    ent = HcsFirmwareUpdateEntity(hass, "entry1")
    assert not (ent._attr_supported_features & UpdateEntityFeature.PROGRESS)
    assert ent._attr_should_poll is False

    ent._checker_info = lambda: {
        "latest_version": "1.0.8",
        "installing": True,
        "outdated_devices": [],
    }
    # Force installed_version via mgr empty → None, so set a stub
    type(ent).installed_version = property(lambda self: "1.0.2")
    assert ent.latest_version == "1.0.2"


def test_firmware_manager_prunes_stale_devices():
    """Powered-off boards must not stay listed; live ones re-register."""
    from datetime import datetime, timedelta, timezone
    import json as _json
    from unittest.mock import MagicMock

    from custom_components.home_climate_control.firmware_manager import (
        FirmwareManager,
        HcsDevice,
    )

    hass = MagicMock()
    hass.config_entries.async_entries.return_value = []
    hass.async_create_task = lambda c: (c.close() if hasattr(c, "close") else None)
    mgr = FirmwareManager(hass)

    old = HcsDevice(node_id="hcs-old", online=False)
    old.last_seen = (
        datetime.now(timezone.utc) - timedelta(hours=2)
    ).isoformat()
    fresh = HcsDevice(node_id="hcs-fresh")
    fresh.last_seen = datetime.now(timezone.utc).isoformat()
    mgr.devices = {"hcs-old": old, "hcs-fresh": fresh}

    msg = MagicMock()
    msg.topic = "hcs/discovery/hcs-fresh"
    msg.payload = _json.dumps(
        {"node_id": "hcs-fresh", "board": "d1_mini", "version": "1.0.2"}
    )
    mgr._on_discovery(msg)

    assert "hcs-old" not in mgr.devices
    assert "hcs-fresh" in mgr.devices
