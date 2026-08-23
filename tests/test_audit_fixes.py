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
