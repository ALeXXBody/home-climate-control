"""Integration test: HCC's OTA trigger — the exact code path used when the
user clicks Install / Flash. Verifies MQTT topic, payload, retain flag and
the HTTP fallback, against mocked HA services."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_hass():
    hass = MagicMock()

    # mqtt component capture
    pub = AsyncMock()
    with patch(
        "custom_components.home_climate_control.firmware_manager.mqtt"
    ) as mqtt_mod:
        mqtt_mod.async_publish = pub
        yield hass, pub


@pytest.mark.asyncio
async def test_trigger_ota_mqtt_topic_payload_nonretained():
    """HCC must publish hcs/<node>/set/ota_url NON-retained (a retained
    ota_url would re-flash the device on every reboot)."""
    gen = _make_hass()
    hass, pub = await gen.__anext__() if False else None, None  # placeholder

    # simpler: build manually
    from unittest.mock import MagicMock as M

    hass = M()
    with patch(
        "custom_components.home_climate_control.firmware_manager.mqtt"
    ) as mqtt_mod:
        pub = AsyncMock()
        mqtt_mod.async_publish = pub

        from custom_components.home_climate_control.firmware_manager import (
            FirmwareManager,
            HcsDevice,
        )

        mgr = FirmwareManager(hass)
        mgr.devices["hcs-test"] = HcsDevice(node_id="hcs-test", ip="10.0.0.5")

        url = "http://192.168.50.20:8123/home_climate_control_static/firmware/firmware-lolin_c3_mini.bin"
        res = await mgr.async_trigger_ota("hcs-test", url)

        assert res["ok"] is True
        pub.assert_awaited_once()
        args, kwargs = pub.await_args.args, pub.await_args.kwargs
        topic, payload = args[1], args[2]
        assert topic == "hcs/hcs-test/set/ota_url"
        assert payload == url
        qos = kwargs.get("qos", args[3] if len(args) > 3 else None)
        retain = kwargs.get("retain", args[4] if len(args) > 4 else None)
        assert qos == 1, "ota_url must use qos 1 so a busy board doesn't miss it"
        assert retain is False, "ota_url must NOT be retained"


@pytest.mark.asyncio
async def test_trigger_ota_no_http_fallback():
    """The HTTP POST fallback was removed: it cannot authenticate to the
    board's (password-protected) control endpoints and was dead weight."""
    from unittest.mock import MagicMock as M

    hass = M()
    session = M()
    session.post = M()

    from custom_components.home_climate_control.firmware_manager import (
        FirmwareManager,
        HcsDevice,
    )

    mgr = FirmwareManager(hass)
    mgr.devices["hcs-t2"] = HcsDevice(node_id="hcs-t2", ip="192.168.50.153")

    with patch(
        "custom_components.home_climate_control.firmware_manager.mqtt"
    ) as mqtt_mod:
        mqtt_mod.async_publish = AsyncMock()
        with patch(
            "custom_components.home_climate_control.firmware_manager.async_get_clientsession",
            return_value=session,
        ):
            url = "http://ha.local/firmware.bin"
            res = await mgr.async_trigger_ota("hcs-t2", url)

            assert res["ok"] is True
            assert res.get("http") is False
            assert not session.post.called
            mqtt_mod.async_publish.assert_awaited_once()
