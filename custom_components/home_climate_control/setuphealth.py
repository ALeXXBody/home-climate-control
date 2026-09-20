"""Setup analysis (generic, rule-based) — capabilities checklist + suggestions.

Produces an ordered list of findings for the app Diagnostics page:

    [{"id", "level", "title", "detail"}, …]

Level:
  ready      — capability available with the current hardware/config
  improvable — works, but a config/hardware addition unlocks more value
  task       — misconfig or missing data that limits core economy features

Everything is derived from the user's own setup (rooms, entities, options);
nothing is hardcoded to any installation.
"""

from __future__ import annotations

READY = "ready"
INFO = "improvable"
TASK = "task"
_TRV_BRANDS_HINT = (
    "TRVs that report valve position (e.g. SONOFF TRVZB, Moes/Tuya eTRV, "
    "Danfoss eTRV) unlock the balancing and metering suggestions"
)

_TRV_BRANDS_HINT = (
    "TRVs that report valve position (e.g. SONOFF TRVZB, Moes/Tuya eTRV, "
    "Danfoss eTRV) unlock balancing suggestions and per-radiator metering"
)


def analyze(entity_ids, opts, rooms) -> list[dict]:
    """Build the capability checklist.

    entity_ids — all HA entity ids visible (for candidate discovery)
    opts       — raw integration options (None-aware)
    rooms      — normalized per-room dicts:
                 {name, has_trv, has_temp, valve_entity, has_lux, has_co2,
                  radiator_kw, window_sensors(list), heat_control,
                  lead_known(bool), setback_mature(bool)}
    """
    entity_ids = list(entity_ids or [])
    rooms = list(rooms or [])
    items = []

    # ── Outdoor temperature ─────────────────────────────────────────────
    outdoor_src = (opts.get("outdoor_source") if isinstance(opts, dict) else None)
    if outdoor_src is None:
        items.append({
            "id": "outdoor",
            "level": TASK,
            "title": "No outdoor temperature",
            "detail": ("Without outdoor data the heating curve and condensing "
                       "pull-down can't run. Assign a boiler outdoor sensor or "
                       "a HA fallback (Configure → outdoor fallback / wind "
                       "entity provides one on many installs)."),
        })
    elif outdoor_src == "boiler_stale":
        items.append({
            "id": "outdoor",
            "level": INFO,
            "title": "Outdoor data is stale",
            "detail": ("Boiler outdoor is older than 30 min and no HA "
                       "fallback is configured — set a fallback sensor for a "
                       "reliable heating curve."),
        })
    else:
        items.append({
            "id": "outdoor",
            "level": READY,
            "title": "Outdoor temperature (" + str(outdoor_src) + ")",
            "detail": "Heating curve and load-aware features active.",
        })

    # ── Auto-tune ────────────────────────────────────────────────────────
    if opts.get("autotune_curve", True):
        items.append({
            "id": "autotune",
            "level": READY,
            "title": "Heating-curve auto-tune",
            "detail": "Curve coefficient is learned from real comfort error.",
        })
    else:
        items.append({
            "id": "autotune",
            "level": INFO,
            "title": "Auto-tune disabled",
            "detail": "Enable it and the curve finds the lowest workable "
                      "flow temperature on its own.",
        })

    # ── Optimal-start readiness (per room) ───────────────────────────────
    unknown = [r["name"] for r in rooms
               if r.get("heat_control") != "manual" and not r.get("lead_known")]
    if rooms and not unknown:
        items.append({
            "id": "preheat",
            "level": READY,
            "title": "Optimal-start pre-heat ready",
            "detail": "Warm-rate and dead-time are learned for every room.",
        })
    elif unknown:
        items.append({
            "id": "preheat",
            "level": TASK if len(unknown) == len(rooms) else INFO,
            "title": "Recovery speed unknown",
            "detail": ("Run Calibrate (or let away/eco cycles learn) for: "
                       + ", ".join(unknown)),
        })

    # ── Smart setbacks maturity ──────────────────────────────────────────
    immature = [r["name"] for r in rooms
                if r.get("heat_control") != "manual" and not r.get("setback_mature")]
    if not immature:
        items.append({
            "id": "setbacks",
            "level": READY,
            "title": "Smart setbacks learned",
            "detail": "Every room has a learned setback depth.",
        })
    else:
        items.append({
            "id": "setbacks",
            "level": INFO,
            "title": "Setback depth still learning",
            "detail": ("Away/eco depth matures after a few cycles for: "
                       + ", ".join(immature)),
        })

    # Manual rooms (heat_control="manual") are observation-only: HCC reads
    # their temperature and nothing else, so no per-room capability item
    # (balancing, metering, solar, CO2) may ask for sensors there.
    smart_rooms = [
        r for r in rooms if r.get("heat_control") != "manual"
    ]

    # ── TRV valve position (balancing) ──────────────────────────────────
    no_valve = [r for r in smart_rooms if not r.get("valve_entity")]
    if smart_rooms and not no_valve:
        items.append({
            "id": "balancing",
            "level": READY,
            "title": "Balancing data available",
            "detail": "Valve position entities assigned for every smart room.",
        })
    elif no_valve:
        names = [r["name"] for r in no_valve]
        cands = _valve_candidates(names, [], entity_ids)
        if cands:
            title = "Valve position not assigned"
            detail = ("Assign a valve-position entity per room to unlock "
                      "balancing suggestions and metering. Candidates "
                      "already visible in HA: " + ", ".join(cands[:4])
                      + ("…" if len(cands) > 4 else ""))
        else:
            title = "TRV does not report valve position"
            detail = ("No valve-position entity found for: "
                      + ", ".join(names)
                      + ". " + _TRV_BRANDS_HINT + ".")
        items.append({
            "id": "balancing",
            "level": INFO,
            "title": title,
            "detail": detail,
        })

    # ── Radiator nominal kW (metering quality) ──────────────────────────
    if smart_rooms and any(r.get("radiator_kw") for r in smart_rooms):
        items.append({
            "id": "radiator_metering",
            "level": READY,
            "title": "Radiator output metering",
            "detail": "Nominal kW set — true per-room radiator output is computed.",
        })
    elif smart_rooms:
        items.append({
            "id": "radiator_metering",
            "level": INFO,
            "title": "Radiator metering inactive",
            "detail": ("Set each room's nominal radiator output (kW @ ΔT50, "
                       "from the radiator datasheet) for true output metering "
                       "and quantified balancing."),
        })

    # ── Tier 3: solar trim ──────────────────────────────────────────────
    if any(r.get("has_lux") for r in smart_rooms):
        items.append({
            "id": "solar",
            "level": READY,
            "title": "Solar-gain trim active",
            "detail": "Sun-warmed rooms drift cooler automatically.",
        })
    elif smart_rooms:
        items.append({
            "id": "solar",
            "level": INFO,
            "title": "No lux sensors",
            "detail": ("A lux/illuminance sensor per sun-exposed room lets "
                       "HCC shave the comfort target while the sun covers "
                       "the heat (small, free savings)."),
        })

    # ── Tier 3: CO₂ ─────────────────────────────────────────────────────
    if any(r.get("has_co2") for r in smart_rooms):
        items.append({
            "id": "co2",
            "level": READY,
            "title": "CO₂ ventilation flags active",
            "detail": "Per-room air quality flags are on.",
        })
    elif smart_rooms:
        items.append({
            "id": "co2",
            "level": INFO,
            "title": "No CO₂ sensors",
            "detail": ("A CO₂ sensor per room drives the needs-ventilation "
                       "flag for HA automations."),
        })

    # ── Schedule ────────────────────────────────────────────────────────
    if opts.get("schedule_entity"):
        items.append({
            "id": "schedule",
            "level": READY,
            "title": "Schedule integration active",
            "detail": str(opts.get("schedule_entity")) +
                      " switches presets automatically.",
        })
    else:
        items.append({
            "id": "schedule",
            "level": INFO,
            "title": "No schedule configured",
            "detail": ("A HA schedule entity (or your own automation) can "
                       "switch comfort/eco for you — biggest saver when "
                       "the house is empty on a schedule."),
        })

    # ── Occupancy ───────────────────────────────────────────────────────
    if opts.get("occupancy_enabled") and opts.get("occupancy_trackers"):
        items.append({
            "id": "occupancy",
            "level": READY,
            "title": "Occupancy auto-setback active",
            "detail": "Presence entities drive the away preset.",
        })
    elif opts.get("occupancy_enabled"):
        items.append({
            "id": "occupancy",
            "level": TASK,
            "title": "Occupancy enabled without trackers",
            "detail": "Select phone/person presence entities or occupancy stays idle.",
        })
    else:
        items.append({
            "id": "occupancy",
            "level": INFO,
            "title": "Occupancy not enabled",
            "detail": ("Phone/device trackers can deep-setback every room "
                       "when everyone is away (optional)."),
        })

    # ── Gas estimate accuracy ───────────────────────────────────────────
    if opts.get("rated_heat_input_kw"):
        items.append({
            "id": "gas",
            "level": READY,
            "title": "Gas estimate has nameplate power",
            "detail": "Boiler heat input configured.",
        })
    else:
        items.append({
            "id": "gas",
            "level": TASK,
            "title": "Gas estimate is a guess",
            "detail": ("Set the boiler's nameplate heat input (kW, the "
                       "value printed as 'central heating input' on the "
                       "data plate) in Configure for real kW estimates."),
        })

    return items


# ── helpers ──────────────────────────────────────────────────────────────
def _valve_candidates(names, trv_suffixes, entity_ids):
    """number.* entities whose id contains the room/TRV slug and 'valve'."""
    out = []
    for name in names:
        slug = str(name).strip().lower().replace(" ", "_")
        for e in entity_ids:
            el = str(e).lower()
            if el.startswith("number.") and "valve" in el and slug and slug in el:
                if e not in out:
                    out.append(e)
    for suf in trv_suffixes:
        s = str(suf).strip().lower().replace(" ", "")
        if not s:
            continue
        for e in entity_ids:
            el = str(e).lower()
            if el.startswith("number.") and "valve" in el and (s in el) and e not in out:
                out.append(e)
    return out
