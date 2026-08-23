"""Tests for the boiler catalog / member-ID mapping."""

from custom_components.home_climate_control.boilers import (
    BOILER_CATALOG,
    MEMBER_ID_TO_MAKE,
    catalog_payload,
    make_for_member,
    models_for_make,
)


def test_vitodens_maps_to_viessmann():
    assert make_for_member(33) == "Viessmann"


def test_sat_known_ids_resolve():
    assert make_for_member(11).startswith("Remeha")
    assert make_for_member(173) == "Intergas"
    assert make_for_member(6) == "Ideal"
    assert make_for_member(27).startswith("Immergas")


def test_unknown_and_zero_are_none():
    assert make_for_member(None) is None
    assert make_for_member(0) is None
    assert make_for_member(250) is None


def test_models_lookup():
    assert "Vitodens 100-W B1KF" in models_for_make("Viessmann")
    assert models_for_make("Nope") == []


def test_catalog_payload_shape():
    p = catalog_payload()
    assert isinstance(p["makes"], list) and p["makes"]
    assert str(33) in p["member_map"]
    assert set(p["models"].keys()) == set(BOILER_CATALOG.keys())


def test_update_version_compare():
    from custom_components.home_climate_control.update_checker import (
        is_newer,
        version_tuple,
    )

    assert version_tuple("v0.9.2") == (0, 9, 2)
    assert is_newer("v0.10.0", "0.9.2")
    assert is_newer("1.0", "0.99.9")
    assert not is_newer("v0.9.2", "0.9.2")
    assert not is_newer(None, "0.9.2")
    assert not is_newer("garbage", "0.9.2")
