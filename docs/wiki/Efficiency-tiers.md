# Efficiency tiers

Practical roadmap for gas-heating efficiency. Each tier adds capability and saves more gas. HCC v1.5.4 implements tiers 0–2 fully (0b learned control, 0c outdoor+curve incl. wind compensation, 1 schedules, 2 occupancy); tiers 3–4 need extra sensors/OT depth.

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
- **Wind compensation** — bounded infiltration trim on the curve (v1.5.4; not a "feels like" value)
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

## Tier 3 — cheap sensors (future)

**Needs:** CO₂ sensors, light sensors per room.

**What you get:**
- CO₂-volume-based ventilation and heating decisions
- Solar gain detection via lux sensors
- Not yet implemented

## Tier 4 — deep OT / radiator fleet (future)

**Needs:** Full OT slave, radiator thermoweb, TRV position feedback.

**What you get:**
- True radiator watt metering
- TRV balancing assistance
- Condensing optimisation with real return temps from radiators
- Partial now (return temp, modulation, ΔT kW available)

## What tier should I aim for?

| Setup | Recommended |
|---|---|
| Basic: room sensors + on/off boiler | Tier 0b (calibrate for smart setbacks) |
| With outdoor sensor | Tier 0c (add heating curve + condensing) |
| Want automation | Tier 1 (add HA schedule) |
| Have phone trackers | Tier 2 (add occupancy) |
| Smart TRVs + outdoor | All of 0b–2 (full stack) |

**Each tier is optional** — you don't need all of them. The system works well at tier 0b and gets progressively better with each addition.
