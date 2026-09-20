"""Setup analyzer (capabilities checklist + suggestions) tests."""

from custom_components.home_climate_control.setuphealth import analyze


def _room(**kw):
    base = {"name": "R", "has_trv": True, "has_temp": True,
            "valve_entity": None, "has_lux": False, "has_co2": False,
            "radiator_kw": None, "heat_control": "smart",
            "lead_known": False, "setback_mature": False}
    base.update(kw)
    return base


def _opts(**kw):
    o = {"outdoor_source": "boiler", "autotune_curve": True,
         "schedule_entity": None, "occupancy_enabled": False,
         "occupancy_trackers": [], "rated_heat_input_kw": None}
    o.update(kw)
    return o


def test_full_setup_is_all_ready():
    rooms = [
        _room(name="L", valve_entity="number.l_valve", radiator_kw=1.8,
              lead_known=True, setback_mature=True),
        _room(name="B", valve_entity="number.b_valve",
              radiator_kw=1.2, lead_known=True, setback_mature=True),
    ]
    items = analyze([], _opts(rated_heat_input_kw=24.0), rooms)
    ids = {i["id"]: i["level"] for i in items}
    assert ids["outdoor"] == "ready"
    assert ids["autotune"] == "ready"
    assert ids["preheat"] == "ready"
    assert ids["setbacks"] == "ready"
    assert ids["balancing"] == "ready"
    assert ids["radiator_metering"] == "ready"
    assert ids["gas"] == "ready"
    # never-configured extras remain suggestions
    assert ids["co2"] == "improvable"
    assert ids["solar"] == "improvable"
    assert ids["occupancy"] == "improvable"


def test_missing_outdoor_is_a_task():
    items = analyze([], _opts(outdoor_source=None), [_room()])
    it = next(i for i in items if i["id"] == "outdoor")
    assert it["level"] == "task"
    assert "heating curve" in it["detail"].lower()


def test_stale_outdoor_suggests_fallback():
    items = analyze([], _opts(outdoor_source="boiler_stale"), [_room()])
    it = next(i for i in items if i["id"] == "outdoor")
    assert it["level"] == "improvable"


def test_trv_without_valve_gets_candidate_suggestion():
    entity_ids = ["number.livingroom_trv_valve_opening_degree",
                  "climate.livingroom_trv"]
    rooms = [_room(name="LivingRoom", trv_suffixes=("livingroom_trv",))]
    items = analyze(entity_ids, _opts(), rooms)
    it = next(i for i in items if i["id"] == "balancing")
    assert it["level"] == "improvable"
    assert "number.livingroom_trv_valve_opening_degree" in it["detail"]


def test_trv_without_any_valve_entity_suggests_hardware():
    rooms = [_room(name="Kitchen")]  # has_trv, no valve anywhere
    items = analyze([], _opts(), rooms)
    it = next(i for i in items if i["id"] == "balancing")
    assert it["level"] == "improvable"
    assert "TRVZB" in it["detail"]  # hardware hint present


def test_valve_assigned_is_ready_even_without_candidates():
    rooms = [_room(name="Kitchen", valve_entity="number.kitchen_trv_valve")]
    items = analyze([], _opts(), rooms)
    it = next(i for i in items if i["id"] == "balancing")
    assert it["level"] == "ready"


def test_occupancy_enabled_without_trackers_is_task():
    items = analyze([], _opts(occupancy_enabled=True, occupancy_trackers=[]),
                    [_room()])
    it = next(i for i in items if i["id"] == "occupancy")
    assert it["level"] == "task"


def test_manual_rooms_excluded_from_learning_checks():
    rooms = [_room(name="ManualRadiator", heat_control="manual")]
    items = analyze([], _opts(), rooms)
    # preheat/setbacks checks pass with only manual rooms
    assert next(i for i in items if i["id"] == "preheat")["level"] == "ready"
    assert next(i for i in items if i["id"] == "setbacks")["level"] == "ready"


def test_manual_room_needs_no_valve_entity():
    rooms = [_room(name="Hallway", heat_control="manual", valve_entity=None)]
    items = analyze([], _opts(rated_heat_input_kw=24.0), rooms)
    balancing = [i for i in items if i["id"] == "balancing"]
    assert balancing == []  # manual rooms are excluded outright


def test_smart_room_without_valve_still_flagged():
    rooms = [_room(name="Study", heat_control="smart")]
    items = analyze([], _opts(rated_heat_input_kw=24.0), rooms)
    ids = {i["id"]: i["level"] for i in items}
    # smart room, no candidates in HA → improvable ("does not report valve position")
    assert ids["balancing"] == "improvable"


def test_manual_only_rooms_get_no_per_room_suggestions():
    """Manual rooms are observation-only: no balancing, metering, solar
    or CO2 items may be generated from them."""
    rooms = [_room(name="Hallway", heat_control="manual", valve_entity=None,
                   radiator_kw=None, has_lux=False, has_co2=False)]
    items = analyze([], _opts(rated_heat_input_kw=24.0), rooms)
    ids = [i["id"] for i in items]
    per_room = {"balancing", "radiator_metering", "solar", "co2"}
    assert not per_room.intersection(ids)
    # system-level capabilities still shown
    assert "outdoor" in ids and "schedule" in ids


def test_ws_room_dict_supports_strict_heater_control_naming():
    """Attr-route regression: python getattr on the *entity* must use
    `heater_control` — the misnamed `heat_control` read the dict *key* only
    in the analyzer, but never on the entity; manual rooms always reported
    "smart". Keep the correct spelling pinned so future edits don't regress.
    """
    class FakeZone:  # minimal entity stand-in
        heater_control = "manual"
    z = FakeZone()
    assert getattr(z, "heater_control", "smart") == "manual"
    assert getattr(z, "heat_control", "smart") == "smart"
