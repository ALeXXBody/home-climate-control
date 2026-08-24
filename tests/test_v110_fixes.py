"""v1.1.0 audit fixes: node-id validation, catalog images, brand icon URL."""

from __future__ import annotations

from pathlib import Path

import pytest

from custom_components.home_climate_control import firmware_manager as fm
from custom_components.home_climate_control.firmware_manager import (
    DEFAULT_CATALOG,
    FirmwareManager,
    catalog_from_releases,
    valid_node_id,
)

WWW_DIR = Path(fm.__file__).parent / "www"
STATIC_PREFIX = "/home_climate_control_static/"


def test_valid_node_id_accepts_real_ids():
    assert valid_node_id("hcs-c4d8d512d085")
    assert valid_node_id("hcs_a1.b2-c3")
    assert valid_node_id("A" * 64)


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "../etc",
        "a/b",
        "hcs/+/set/x",
        "#",
        "node id with spaces",
        ".hidden",
        "-lead",
        None,
        123,
        "x" * 65,
    ],
)
def test_valid_node_id_rejects_unsafe(bad):
    assert not valid_node_id(bad)


def _mgr() -> FirmwareManager:
    from unittest.mock import MagicMock

    return FirmwareManager(MagicMock())


@pytest.mark.asyncio
async def test_send_control_rejects_bad_node():
    res = await _mgr().async_send_control("../x", "ch_enable", True)
    assert not res["ok"] and "invalid node" in res["error"]


@pytest.mark.asyncio
async def test_wc_curve_rejects_bad_node():
    res = await _mgr().async_apply_wc_curve("a/b", {"wc_ref": 1})
    assert not res["ok"] and "invalid node" in res["error"]


@pytest.mark.asyncio
async def test_push_settings_rejects_bad_node():
    res = await _mgr().async_push_settings("../x", {"device_name": "y"})
    assert not res["ok"] and "invalid node" in res["error"]


@pytest.mark.asyncio
async def test_trigger_ota_rejects_bad_node():
    res = await _mgr().async_trigger_ota("a/b", "http://x/firmware-d1_mini.bin")
    assert not res["ok"] and "invalid node" in res["error"]
    # mirror side effects must not have run for a bad node
    assert _mgr().last_ota_url is None


@pytest.mark.asyncio
async def test_reboot_rejects_bad_node():
    res = await _mgr().async_reboot("#")
    assert not res["ok"] and "invalid node" in res["error"]


def test_default_catalog_images_resolve_on_disk():
    for item in DEFAULT_CATALOG:
        rel = item["image"]
        assert rel.startswith(STATIC_PREFIX), item
        assert (WWW_DIR / rel[len(STATIC_PREFIX):]).is_file(), item


def test_generated_catalog_images_resolve_on_disk():
    """Live-release entries inherit base art; unknown boards get the SVG."""
    releases = [
        {
            "tag_name": "v9.9.9",
            "draft": False,
            "prerelease": False,
            "assets": [
                {
                    "name": f"firmware-{b}.bin",
                    "browser_download_url": (
                        "https://github.com/ALeXXBody/home-climate-system/"
                        f"releases/download/v9.9.9/firmware-{b}.bin"
                    ),
                }
                for b in ("d1_mini", "lolin_s2_mini_gw", "brand_new_board")
            ],
        }
    ]
    entries = catalog_from_releases(releases, DEFAULT_CATALOG)
    by_board = {e["board"]: e for e in entries}
    # known boards reuse bundled metadata (photo or svg — both exist)
    assert (WWW_DIR / by_board["d1_mini"]["image"][len(STATIC_PREFIX):]).is_file()
    assert (
        WWW_DIR / by_board["lolin_s2_mini_gw"]["image"][len(STATIC_PREFIX):]
    ).is_file()
    # unknown board falls back to the per-board SVG, never a missing photo
    fallback = by_board["brand_new_board"]["image"]
    assert fallback == STATIC_PREFIX + "boards/brand_new_board.svg"
    # ...and every *shipped* board's SVG actually exists
    assert (WWW_DIR / "boards" / "d1_mini.svg").is_file()


def test_brand_icon_url_points_at_served_copy():
    from custom_components.home_climate_control.update import HcsFirmwareUpdateEntity

    entity = object.__new__(HcsFirmwareUpdateEntity)
    url = HcsFirmwareUpdateEntity._brand_icon_url(entity)
    assert url is not None
    assert url.startswith(STATIC_PREFIX + "brand/icon.png")
