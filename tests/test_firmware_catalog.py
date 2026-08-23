"""Dynamic firmware catalog from GitHub releases (pill fix)."""

from custom_components.home_climate_control.firmware_manager import (
    DEFAULT_CATALOG,
    catalog_from_releases,
)

RELEASES = [
    {
        "tag_name": "v1.1.0",
        "name": "v1.1.0 — Auto-detect probes",
        "draft": False,
        "prerelease": False,
        "published_at": "2026-08-23T20:00:00Z",
        "assets": [
            {"name": "firmware-d1_mini.bin", "browser_download_url": "u-d1"},
            {
                "name": "firmware-lolin_c3_mini.bin",
                "browser_download_url": "u-c3",
            },
            {"name": "source.zip", "browser_download_url": "u-src"},
        ],
    },
    {
        "tag_name": "v1.0.2",
        "draft": False,
        "prerelease": False,
        "published_at": "2026-08-01T10:00:00Z",
        "assets": [{"name": "firmware-esp32_d1_mini.bin", "url": "u-e32"}],
    },
]


def test_entries_from_release_assets():
    cat = catalog_from_releases(RELEASES, DEFAULT_CATALOG)
    d1 = next(e for e in cat if e["board"] == "d1_mini" and e["version"] == "1.1.0")
    assert d1["id"] == "hcs-1.1.0-d1_mini"
    assert d1["url"] == "u-d1"
    # newest release first in ordering
    first_board_pos = [e["board"] for e in cat]
    assert "esp32_d1_mini" not in first_board_pos[:2]  # older release later
    c3 = [e for e in cat if e["board"] == "lolin_c3_mini" and e["version"] == "1.1.0"]
    assert c3 and c3[0]["url"] == "u-c3"


def test_metadata_inherited_from_bundled_base():
    cat = catalog_from_releases(RELEASES, DEFAULT_CATALOG)
    base_d1 = next(b for b in DEFAULT_CATALOG if b["board"] == "d1_mini")
    d1 = next(
        e for e in cat if e["board"] == "d1_mini" and e["version"] == "1.1.0"
    )
    assert d1["model"] == base_d1["model"]
    assert d1["image"] == base_d1["image"]
    assert d1["description"] == base_d1["description"]
    # title carries the NEW version, not the bundled one
    assert "1.1.0" in d1["title"]


def test_bundled_fallback_not_duplicated_but_kept():
    cat = catalog_from_releases([], DEFAULT_CATALOG)  # GitHub unreachable
    boards = [(e["board"], e["version"]) for e in cat]
    assert ("d1_mini", "1.0.2") in boards

    cat2 = catalog_from_releases(RELEASES, DEFAULT_CATALOG)
    keys = [(e["board"], e["version"]) for e in cat2]
    # v1.1.0 covers d1_mini; bundled 1.0.2 d1 stays as fallback but only once
    assert keys.count(("d1_mini", "1.0.2")) == 1
    assert keys.count(("d1_mini", "1.1.0")) == 1


def test_draft_prerelease_and_bad_assets_skipped():
    rels = [
        {
            "tag_name": "v9.9.9",
            "draft": True,
            "assets": [{"name": "firmware-d1_mini.bin"}],
        },
        {
            "tag_name": "v2.0.0-rc1",
            "prerelease": True,
            "assets": [{"name": "firmware-d1_mini.bin"}],
        },
    ]
    cat = catalog_from_releases(rels, [])
    assert cat == []
