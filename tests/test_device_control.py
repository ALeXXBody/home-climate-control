"""Board Control-page replication over MQTT (device_control)."""

from __future__ import annotations

import asyncio
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
        node_id="hcs-a", name="Boiler GW", board="lolin_c3_mini", version="1.2.2"
    )
    return m


def _msg(topic, payload):
    m = MagicMock()
    m.topic = topic
    m.payload = payload if isinstance(payload, str) else json.dumps(payload)
    return m


def test_send_control_formats_payloads(mgr):
    from homeassistant.components import mqtt

    res = asyncio.run(mgr.async_send_control("hcs-a", "ch_enable", True))
    assert res["ok"]
    topic, payload = mqtt.async_publish.call_args[0][1:3]
    assert (topic, payload) == ("hcs/hcs-a/set/ch_enable", "true")

    asyncio.run(mgr.async_send_control("hcs-a", "max_modulation", 75))
    assert mqtt.async_publish.call_args[0][2] == "75"

    asyncio.run(mgr.async_send_control("hcs-a", "flow_setpoint", 47.25))
    assert float(mqtt.async_publish.call_args[0][2]) == pytest.approx(47.2)

    asyncio.run(mgr.async_send_control("hcs-a", "dhw_setpoint", "auto"))
    assert mqtt.async_publish.call_args[0][2] == "auto"

    asyncio.run(mgr.async_send_control("hcs-a", "dhw_setpoint", 50))
    assert mqtt.async_publish.call_args[0][2] == "50.0"


def test_send_control_rejects_bad_keys(mgr):
    from homeassistant.components import mqtt

    assert not asyncio.run(
        mgr.async_send_control("hcs-a", "wc_ref", 20)
    )["ok"]  # curves go through async_apply_wc_curve
    assert not asyncio.run(mgr.async_send_control("ghost", "ch_enable", True))["ok"]
    assert not asyncio.run(mgr.async_send_control("hcs-a", "reboot", True))["ok"]
    # nothing published for rejected calls
    assert not any(
        c[0][1].endswith("/reboot") for c in mqtt.async_publish.call_args_list
    )


def test_apply_wc_curve_body(mgr):
    from homeassistant.components import mqtt

    res = asyncio.run(
        mgr.async_apply_wc_curve(
            "hcs-a",
            {"wc_ref": 18, "wc_design": -10, "wc_fmax": 65, "wc_fmin": 25},
        )
    )
    assert res["ok"]
    topic, payload = mqtt.async_publish.call_args[0][1:3]
    assert topic == "hcs/hcs-a/set/weather_comp_cfg"
    assert json.loads(payload) == {
        "t_out_ref": 18.0,
        "t_out_design": -10.0,
        "flow_max": 65.0,
        "flow_min": 25.0,
    }


def test_on_ctl_parses_snapshot_and_tolerates_garbage(mgr):
    snap = {
        "ch_enable": False,
        "dhw_enable": True,
        "dhw_setpoint": None,
        "flow_setpoint": 45,
        "max_modulation": 100,
        "wc_enable": True,
        "wc_ref": 18,
        "wc_design": -10,
        "wc_fmax": 65,
        "wc_fmin": 25,
        "wc_target": 38.5,
        "fs_state": "OFF",
    }
    mgr._on_ctl(_msg("hcs/hcs-a/ctl", json.dumps(snap)))
    assert mgr.devices["hcs-a"].ctl == snap
    # garbage never clobbers state; unknown devices ignored
    mgr._on_ctl(_msg("hcs/hcs-a/ctl", "{bogus"))
    assert mgr.devices["hcs-a"].ctl == snap
    dev = HcsDevice(node_id="hcs-b")
    mgr.devices["hcs-b"] = dev
    mgr._on_ctl(_msg("hcs/unknown/ctl", json.dumps(snap)))
    assert dev.ctl == {}
