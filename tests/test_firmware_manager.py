"""Tests for the firmware catalog and board-match guard."""

from __future__ import annotations

import pytest

from custom_components.home_climate_control.firmware_manager import (
    DEFAULT_CATALOG,
    HcsDevice,
    catalog_item,
)


def test_catalog_covers_all_boards() -> None:
    boards = {item["board"] for item in DEFAULT_CATALOG}
    assert {
        "d1_mini",
        "lolin_s2_mini",
        "lolin_c3_mini",
        "esp32_d1_mini",
        "esp32s3_zero",
        "lolin_s2_mini_gw",
        "esp32_d1_mini_gw",
        "lolin_c3_mini_gw",
    } <= boards


def test_catalog_urls_match_release_assets() -> None:
    for item in DEFAULT_CATALOG:
        assert item["version"] == "1.0.1"
        assert item["url"].startswith(
            "https://github.com/ALeXXBody/home-climate-system/releases/download/v1.0.1/"
        )
        assert item["url"].endswith(f"firmware-{item['board']}.bin")


def test_catalog_item_lookup() -> None:
    assert catalog_item(DEFAULT_CATALOG, "hcs-1.0.1-lolin_c3_mini") is not None
    assert catalog_item(DEFAULT_CATALOG, "nope") is None


@pytest.mark.parametrize(
    ("dev_board", "img_board", "should_block"),
    [
        ("d1_mini", "d1_mini", False),
        # gateway image on base-flashed device of same family is allowed
        ("lolin_c3_mini", "lolin_c3_mini_gw", False),
        ("lolin_s2_mini", "lolin_s2_mini_gw", False),
        # cross-family must be blocked
        ("lolin_c3_mini", "d1_mini", True),
        ("esp32s3_zero", "lolin_c3_mini", True),
        ("", "d1_mini", False),  # unknown board -> no guard
    ],
)
def test_board_guard_logic(dev_board: str, img_board: str, should_block: bool) -> None:
    """Mirror of the ws_flash_device guard predicate."""
    dev = HcsDevice(node_id="n", board=dev_board)
    blocked = (
        dev.board != img_board
        and not dev.board.startswith(img_board)
        and not img_board.startswith(dev.board)
        and bool(dev.board)
    )
    assert blocked is should_block
