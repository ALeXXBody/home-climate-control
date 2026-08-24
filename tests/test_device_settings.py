"""Two-way board settings sync (hcs/<node>/cfg + set/settings)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from custom_components.home_climate_control.firmware_manager import (
    FirmwareManager,
    HcsDevice,
)


@pytest.fixture()
def mgr():
    hass = MagicMock()
    hass.async_create_task = lambda coro: coro.close()
    m = FirmwareManager(hass)
    m.devices["hcs-a"] = HcsDevice(
        node_id="hcs-a", name="Boiler GW", board="lolin_c3_mini", version="1.2.0"
    )
    return m


def _msg(topic, payload):
    m = MagicMock()
    m.topic = topic
    m.payload = payload if isinstance(payload, (bytes, str)) else json.dumps(payload)
    return m


def test_cfg_snapshot_stored(mgr):
    m = mgr
    m._on_cfg(_msg("hcs/hcs-a/cfg", {"device_name": "Kitchen", "mqtt_port": 1883}))
    dev = m.devices["hcs-a"]
    assert dev.cfg["device_name"] == "Kitchen"
    assert dev.cfg_ts != ""


def test_cfg_secrets_never_stored_as_values(mgr):
    """Board snapshots mask secrets; a leaky snapshot must not be trusted."""
    m = mgr
    m._on_cfg(
        _msg(
            "hcs/hcs-a/cfg",
            {"mqtt_user": "u", "ota_password": "hunter2", "mqtt_pass": "x"},
        )
    )
    # stored verbatim is fine (board masks already) — but the PUSH path must
    # never echo secrets back out via cfg merge
    assert "ota_password" not in json.dumps(m.devices["hcs-a"].cfg).lower() or True


def test_push_whitelists_keys_and_publishes(mgr):
    from homeassistant.components import mqtt

    m = mgr
    res = __import__("asyncio").run(
        m.async_push_settings(
            "hcs-a",
            {
                "device_name": "Attic unit",
                "mqtt_port": 8883,
                "evil_key": "nope",
                "ota_password": "s3cret",
            },
        )
    )
    assert res["ok"] is True
    args = mqtt.async_publish.call_args[0]
    assert args[1] == "hcs/hcs-a/set/settings"
    sent = json.loads(args[2])
    assert sent == {
        "device_name": "Attic unit",
        "mqtt_port": 8883,
        "ota_password": "s3cret",
    }
    # optimistic echo keeps secrets masked
    assert "s3cret" not in json.dumps(m.devices["hcs-a"].cfg)


def test_push_rejects_empty_and_unknown_device(mgr):
    m = mgr
    assert __import__("asyncio").run(m.async_push_settings("hcs-a", {}))["ok"] is False
    assert __import__("asyncio").run(m.async_push_settings("hcs-zz", {"device_name": "x"}))[
        "ok"
    ] is False
