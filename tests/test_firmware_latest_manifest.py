"""The pre-mirror contract (v1.26.1): a manifest row can only exist for a
board whose image was pre-mirrored onto the hub's static route. v1.26.0
written a manifest while its pre-mirror fetch failed → boards pulling
latest.json → 404 on the bin — the pull branch broken again after 1.5.30's
push fixes."""

import asyncio
import hashlib
import json
import tempfile
from pathlib import Path as P
from unittest.mock import AsyncMock, MagicMock

import pytest

import custom_components.home_climate_control.firmware_manager as fm

from custom_components.home_climate_control.firmware_manager import (
    FirmwareManager,
)

FW = b"fw-bytes" + b"B" * 1200
DIGEST = hashlib.sha256(FW).hexdigest()


def _build(mirror: P):
    hass = MagicMock()
    mgr = FirmwareManager(hass)
    mgr.MIRROR_DIR = mirror
    return mgr, hass


def test_manifest_without_pre_mirror_is_withheld(tmp_path):
    mirror = P(tmp_path)
    mgr, hass = _build(mirror)

    async def _fetch_bin(url):
        raise RuntimeError("mirror failed (zombie/zombie/zombie from Oct)")

    mgr._async_fetch_bin = _fetch_bin

    async def _drive():
        await mgr._async_write_latest_manifest([
            {"board": "esp32_d1_mini", "version": "1.5.30",
             "sha256": DIGEST, "url": "https://x/fw.bin"},
        ])

    asyncio.run(_drive())
    assert not (mirror / "latest.json").exists()
    assert not (mirror / "firmware-esp32_d1_mini.bin").exists()


def test_manifest_with_served_bin_matches_and_lists(tmp_path):
    mirror = P(tmp_path)
    mgr, hass = _build(mirror)

    async def _fetch_bin(url):
        return FW

    mgr._async_fetch_bin = _fetch_bin

    async def _drive():
        await mgr._async_write_latest_manifest([
            {"board": "esp32_d1_mini", "version": "1.5.30",
             "sha256": DIGEST, "url": "https://x/fw.bin"},
        ])

    asyncio.run(_drive())
    served = mirror / "firmware-esp32_d1_mini.bin"
    assert served.is_file()
    assert hashlib.sha256(served.read_bytes()).hexdigest() == DIGEST
    row = json.loads((mirror / "latest.json").read_text())["boards"]["esp32_d1_mini"]
    assert row["version"] == "1.5.30"
    assert row["url"].endswith("/firmware-esp32_d1_mini.bin")


def test_manifest_prefers_newest_signed_row(tmp_path):
    mirror = P(tmp_path)
    fw28 = b"fw-1.5.28"
    fw30 = b"fw-1.5.30"
    mgr, hass = _build(mirror)

    async def _fetch_bin(url):
        return fw28 if url.endswith("firmware-esp32_d1_mini28.bin") else fw30

    mgr._async_fetch_bin = _fetch_bin

    async def _drive():
        await mgr._async_write_latest_manifest([
            {"board": "esp32_d1_mini", "version": "1.5.28", "sha256": "ab" * 32,
             "url": "https://x/firmware-esp32_d1_mini28.bin"},
            {"board": "esp32_d1_mini", "version": "1.5.30",
             "sha256": hashlib.sha256(fw30).hexdigest(),
             "url": "https://x/fw.bin"},
        ])

    asyncio.run(_drive())
    row = json.loads((mirror / "latest.json").read_text())["boards"]["esp32_d1_mini"]
    assert row["version"] == "1.5.30"
    served = (mirror / "firmware-esp32_d1_mini.bin").read_bytes()
    assert served == fw30
