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
async def test_trigger_ota_dual_channel_http_and_mqtt():
    """v1.25.1: the OTA delivery re-audited. The MQTT-only path silently
    failed in the Oct 2026 zombie-session incident (the publish returned
    clean while the socket was dead); the ten failed updates ended there.
    The delivery now rides BOTH channels: HTTP-direct to the board's own
    portal (authenticated with the stored board password) first, MQTT as
    the fallback when the board's HTTP is unreachable."""
    from unittest.mock import MagicMock as M

    hass = M()
    session = M()

    class _RespCtx:
        status = 200
        async def __aenter__(self):
            return self
        async def __aexit__(self, *e):
            return False
    session.post = M(return_value=_RespCtx())

    from custom_components.home_climate_control.firmware_manager import (
        FirmwareManager,
        HcsDevice,
    )
    mgr = FirmwareManager(hass)
    mgr.devices["hcs-t2"] = HcsDevice(node_id="hcs-t2", ip="192.168.50.153")
    mgr._board_admin_pw = {"hcs-t2": "test1234"}

    with patch(
        "custom_components.home_climate_control.firmware_manager.mqtt"
    ) as mqtt_mod:
        mqtt_mod.async_publish = AsyncMock()
        with patch(
            "custom_components.home_climate_control.firmware_manager."
            "async_get_clientsession",
            return_value=session,
        ):
            url = "http://ha.local/firmware.bin"
            res = await mgr.async_trigger_ota("hcs-t2", url)

            assert res["ok"] is True
            assert res.get("http") is True      # direct channel fired
            assert session.post.called          # the portal was POSTed
            mqtt_mod.async_publish.assert_awaited_once()

def test_catalog_refresh_writes_latest_json_for_boards():
    """The hub publishes latest.json beside the mirrored firmware: the boards
    read THIS over plain LAN HTTP for their pull-based self-update. Newer
    release per board wins; entries without sha256 are excluded (signed-only
    reach)."""
    import asyncio, json, tempfile
    from unittest.mock import MagicMock, patch

    from custom_components.home_climate_control.firmware_manager import (
        FirmwareManager,
    )

    tmp = tempfile.mkdtemp()
    hass_obj = MagicMock()
    with patch.object(FirmwareManager, "MIRROR_DIR", None):
        pass  # MIRROR_DIR as class attr gets monkeypatched below
    mgr = FirmwareManager(hass_obj)
    import pathlib

    import pytest

    mirror = pathlib.Path(tmp)
    with patch.object(FirmwareManager, "MIRROR_DIR", mirror):
        entries = [
            {"board": "esp32_d1_mini", "version": "1.5.28", "sha256": "aa"},
            {"board": "esp32_d1_mini", "version": "1.5.30", "sha256": "bb"},
            {"board": "esp32_d1_mini", "version": "1.5.31", "sha256": ""},  # unsigned→ excluded
            {"board": "esp32_test", "version": "9.9.9", "url": "http://x"},
            {
                "url": "https://github.com/ALeXXBody/home-climate-system/releases/download/v1.5.30/firmware-esp32_d1_mini.bin",
                "version": "1.5.30",
                "board": "esp32_d1_mini",
                "sha256": "bb",
                "size": 1300128,
            },
        ]
        mgr._async_write_latest_manifest(entries)
        data = json.loads((mirror / "latest.json").read_text())
        board = data["boards"]["esp32_d1_mini"]
        assert board["version"] == "1.5.30"       # newest signed wins
        assert board["url"].endswith("/firmware-esp32_d1_mini.bin")
