"""Freshness-checked LAN mirror for release binaries (stale-image fix)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from custom_components.home_climate_control import firmware_manager as fm
from custom_components.home_climate_control.firmware_manager import (
    FirmwareManager,
    HcsDevice,
)

GH = (
    "https://github.com/ALeXXBody/home-climate-system/releases/download/"
    "v1.1.1/firmware-d1_mini.bin"
)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(FirmwareManager, "MIRROR_DIR", tmp_path)
    hass = MagicMock()
    m = FirmwareManager(hass)
    m.catalog = [
        {"board": "d1_mini", "version": "1.1.1", "size": "70000", "url": GH},
    ]
    return m, tmp_path


def _fake_session(payload: bytes, calls: list):
    class _Resp:
        def raise_for_status(self):
            pass

        async def read(self):
            return payload

    class _CM:
        async def __aenter__(self):
            calls.append(GH)
            return _Resp()

        async def __aexit__(self, *a):
            return False

    class _Sess:
        def get(self, url):
            return _CM()

    return _Sess()


def test_non_release_urls_pass_through(env):
    m, _ = env
    assert asyncio.run(m._async_ota_url("http://lan/fw.bin")) == "http://lan/fw.bin"


def test_fresh_cache_not_redownloaded(env, monkeypatch):
    m, tmp = env
    f = tmp / "firmware-d1_mini.bin"
    f.write_bytes(b"1" * 70000)  # matches catalog size
    calls = []
    monkeypatch.setattr(fm, "async_get_clientsession", lambda h: _fake_session(b"x" * 70000, calls))
    url = asyncio.run(m._async_ota_url(GH))
    assert calls == []  # no download: cache already fresh
    assert url == "http://192.168.50.20:8123/home_climate_control_static/firmware/firmware-d1_mini.bin"


def test_stale_cache_is_refreshed_before_mirroring(env, monkeypatch):
    """The v1.0.2-forever bug: old cached image was served verbatim."""
    m, tmp = env
    f = tmp / "firmware-d1_mini.bin"
    f.write_bytes(b"old-image!")  # wrong size -> stale
    calls = []
    monkeypatch.setattr(fm, "async_get_clientsession", lambda h: _fake_session(b"A" * 70000, calls))
    url = asyncio.run(m._async_ota_url(GH))
    assert calls == [GH]  # refresh happened
    assert f.read_bytes() == b"A" * 70000
    assert url.endswith("/home_climate_control_static/firmware/firmware-d1_mini.bin")


def test_missing_cache_downloads_and_serves(env, monkeypatch):
    m, tmp = env
    calls = []
    monkeypatch.setattr(fm, "async_get_clientsession", lambda h: _fake_session(b"B" * 70000, calls))
    url = asyncio.run(m._async_ota_url(GH))
    assert (tmp / "firmware-d1_mini.bin").read_bytes() == b"B" * 70000
    assert url.endswith("/firmware/firmware-d1_mini.bin")


def test_failed_download_keeps_old_cache(env, monkeypatch):
    m, tmp = env
    f = tmp / "firmware-d1_mini.bin"
    f.write_bytes(b"keep")

    class _Boom:
        def get(self, url):
            raise TimeoutError()

    monkeypatch.setattr(fm, "async_get_clientsession", lambda h: _Boom())
    url = asyncio.run(m._async_ota_url(GH))
    assert f.read_bytes() == b"keep"  # old image still served
    assert url.endswith("/firmware/firmware-d1_mini.bin")


def test_trigger_publishes_mirrored_url(env, monkeypatch):
    """End-to-end: flash command must hand the board the LAN mirror URL."""
    from homeassistant.components import mqtt

    m, tmp = env
    dev = HcsDevice(node_id="hcs-x", board="d1_mini")
    m.devices["hcs-x"] = dev
    f = tmp / "firmware-d1_mini.bin"
    f.write_bytes(b"C" * 5)
    res = asyncio.run(m.async_trigger_ota("hcs-x", GH, target_version="1.1.1"))
    assert res["ok"] is True
    args = mqtt.async_publish.call_args[0]
    assert "/home_climate_control_static/firmware/firmware-d1_mini.bin" in args[2]
    assert dev.ota_target_version == "1.1.1"
