# Efficiency tiers

Practical roadmap for gas-heating efficiency. Each tier adds capability and saves more gas. HCC v1.5.5 implements tiers 0–2 fully (0b learned control, 0c outdoor+curve incl. wind compensation, 1 schedules, 2 occupancy); tiers 3–4 need extra sensors/OT depth.

## Tier 0 — room temp + boiler switch

**Needs:** Room temperature sensor, basic boiler on/off.

**What you get:**
- Room-level climate control (heat/off per zone)
- Window/door sensor pause
- Basic setback presets (eco, night, away)

**No outdoor temp, no curve, no learning.**

## Tier 0b — learned control

**Needs:** Same as 0, plus a few heating cycles for data.

**What you get:**
- **Bootstrap calibration** — one click measures °C/h warm-up and seeds the learner
- **Dead-time learning** — minutes between enabling heat and temp rising
- **Optimal-start pre-heat** — `lead = dead_time + deficit/warm_rate + margin`
- **Smart setbacks** — learned night/away depth per room from recovery speed
- **CycleGuard** — adaptive burner rest + minimum-on floor
- **Slope open-window detection** — no contact sensor needed
- **Load-aware health flags** — patience scales with outdoor load
- **Estimated gas** (modulation-based)
- **Low-load duty cycling** — PWM below min modulation

## Tier 0c — outdoor + curve

**Needs:** Outdoor temperature source (boiler OT sensor or HA fallback).

**What you get:**
- **Heating curve** — outdoor→flow mapping
- **Auto-tune curve** — learns optimal coefficient
- **Outdoor HA fallback** — boiler → HA sensor → stale boiler → none
- **Wind compensation** — bounded infiltration trim on the curve (v1.5.5; not a "feels like" value)
- **Condensing pull-down** — shaves flow when return >54 °C
- **Load-aware health** (improved with outdoor data)
- **Gas ΔT estimate** — `P_max × ΔT/20K / η` when mod% is 0
- **Hydronic kW** — `flow × ΔT × k`

## Tier 1 — internet / HA helpers

**Needs:** Home Assistant helpers (schedule, input_select).

**What you get:**
- **HA schedule → presets** — time-based preset switching
- **Any HA automation** can set presets via input_select/sensor

## Tier 2 — phones / contacts

**Needs:** Phone trackers (`device_tracker.*`, `person.*`).

**What you get:**
- **Occupancy auto-setback** — all away → deep setback
- **Pre-heat before arrival** — dead-time lead calculates recovery
- Works with schedule: schedule drives home, occupancy handles absence

## Tier 3 — cheap sensors ✅ (v1.7.0)

**Needs:** CO₂ sensor and/or lux sensor per room (optional).

**What you get:**
- **Solar gain trim** — a sunlit room (lux > 5000, hysteresis) shaves 0.5 °C off the comfort target automatically; radiant warmth covers it, gas doesn't
- **CO₂ ventilation flag** — per-room "needs ventilation" (CO₂ > 1100 ppm, clears < 800) surfaced in the panel/attributes for HA automations (heating is deliberately NOT paused on CO₂ — comfort first)

## Tier 4 — deep OT / radiator fleet ✅ (v1.7.0, partial)

**Implemented (v1.7.0):**
- **True radiator metering** — set a room's nominal radiator kW (ΔT50 rating) and HCC computes the actual output from real OT flow/return/room temps: `Q = nominal × (ΔT/50)^1.3`
- **TRV balancing assistance** — assign a valve-position entity (0–100 %) and HCC builds a 2-hour picture: `undersupplied` (valve pegged open, room cold), `oversupplied` (valve closed, room warm), or `ok`

**Still future:** full OT slave depth, per-radiator thermoweb, automatic lockshield suggestions

## What tier should I aim for?

| Setup | Recommended |
|---|---|
| Basic: room sensors + on/off boiler | Tier 0b (calibrate for smart setbacks) |
| With outdoor sensor | Tier 0c (add heating curve + condensing) |
| Want automation | Tier 1 (add HA schedule) |
| Have phone trackers | Tier 2 (add occupancy) |
| Smart TRVs + outdoor | All of 0b–2 (full stack) |

**Each tier is optional** — you don't need all of them. The system works well at tier 0b and gets progressively better with each addition.
