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
        assert retain is False, "ota_url must NOT be retained"


@pytest.mark.asyncio
async def test_trigger_ota_http_fallback_called():
    from unittest.mock import MagicMock as M

    hass = M()
    session = M()
    resp = M()
    resp.status = 200

    class _RespCtx:  # noqa: D401 - async context manager for "async with"
        async def __aenter__(self):
            return resp

        async def __aexit__(self, *a):
            return False

    post_calls = []

    class _PostFn:
        call_args = None
        async_count = 0
        _calls = post_calls

        def __call__(self, *a, **k):
            post_calls.append((a, k))
            return _RespCtx()

    session.post = _PostFn()


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
            assert res.get("http") is True
            assert not res.get("http_error")
            a, kw = post_calls[-1]
            assert a[0] == "http://192.168.50.153/api/ota"
            assert kw.get("json") == {"url": url}
            assert kw.get("timeout") == 30
