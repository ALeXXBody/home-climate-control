# Options & settings

Open integration **Configure** from **Settings → Devices & services → Home Climate Control → Configure**.

## Core control

| Option | Default | Description |
|---|---|---|
| Min flow temperature | 25 °C | Lowest allowed flow setpoint (boiler clamp) |
| Max flow temperature | 75 °C | Highest allowed flow setpoint (boiler clamp) |
| Heating curve coefficient | 1.2 | Slope of outdoor→flow mapping; auto-tune adjusts over time |
| Auto-tune curve | on | Learns optimal coefficient from real comfort error |
| Learn smart setbacks | on | Learns night/away depth per room from recovery speed |

## Outdoor temperature

| Option | Default | Description |
|---|---|---|
| Outdoor temperature fallback | — | `sensor.*` or `weather.*` entity; used when boiler outdoor is missing or stale (>30 min) |
| Weather entity for wind | — | `weather.*` entity providing `wind_speed` — **selecting one enables wind compensation** |
| Wind trim cap | 3 °C | Maximum curve trim from wind |

## Wind compensation (optional — off by default)

Wind raises building heat loss through infiltration. When enabled, HCC
trims the outdoor temperature **the heating curve sees**:

```
trim = min(cap, 0.25 × wind_kmh^0.9)   effective_outdoor = outdoor − trim
```

- **Not** a weather-app "feels like" value — skin wind-chill would
  over-heat the building. This is a bounded infiltration correction
  (same idea commercial weather compensators call a "chill factor").
- Systemic benefit: windy-day cold rooms no longer push auto-tune to
  inflate the curve coefficient (which overshoots calm days) — the
  learned coefficient settles lower and steadier.
- Raw outdoor stays untouched for display, logging, and the Diagnostics
  tab shows the current wind, trim and cap.

**Priority chain:** boiler outdoor (fresh, <30 min) → HA fallback sensor → stale boiler → none.

When outdoor temp is unavailable, the heating curve can't calculate a target — the system falls back to the last known flow setpoint or manual control.

## Low-load duty cycling

| Option | Default | Description |
|---|---|---|
| Boiler min modulation % | 20 | Below this, the boiler can't modulate lower — duty cycle activates |
| Low-load duty cycling | on | PWMs CH on/off when demand is below boiler minimum |

**How it works:** When heat demand exists but is below the boiler's minimum modulation, the system alternates between longer ON and OFF periods instead of running the boiler at its minimum the whole time. This saves gas by avoiding the inefficiency of very low modulation.

The cycle period adapts to outdoor load — colder days = shorter cycles (more responsive), mild days = longer cycles (more efficient).

## HA schedule → presets

| Option | Default | Description |
|---|---|---|
| Heating schedule entity | — | `schedule.*`, `input_select.*`, or `sensor.*` entity |
| Schedule on preset | comfort | Preset applied when schedule window is ON |
| Schedule off preset | eco | Preset applied when schedule window is OFF |

See [Schedule → presets](Schedule.md) for full details.

## Phone occupancy (optional — off by default)

| Option | Default | Description |
|---|---|---|
| Occupancy auto-setback | **off** | Master switch — must be on for any presence logic |
| Presence entities | — | `device_tracker.*`, `person.*`, or presence `binary_sensor.*` |
| Occupancy away preset | away | Preset applied to all smart rooms when everyone is away |
| Occupancy home preset | comfort | Preset applied when anyone is home (schedule takes priority if set) |

See [Occupancy](Occupancy.md) for full details.

## Gas metering

| Option | Default | Description |
|---|---|---|
| Gas nameplate input kW | 0 | Your boiler's rated heat input (not output) — needed for ΔT estimate |
| Gas min input kW | 0 | Minimum modulation in kW — improves low-load estimate accuracy |
| Gas nomod factor | 0.7 | Fallback modulation multiplier when OT reports 0% but flame is on |
| Gas calibration | 1.0 | Multiplier applied to all estimates (calibrate against your meter) |
| Gas price | 0 | Price per unit (for cost display) |
| Gas meter name | — | Custom entity name |

**Estimation modes:**
- **Modulation** — default when OT modulation is available; `mod% × nameplate × factor`
- **ΔT estimate** — used when mod% is 0 but flame is on; `P_max × ΔT/20K / η`
- **Hydronic kW** — `flow × (flow - return) × k`; accurate with good return sensor

See [Gas metering](Gas-metering.md) for full details.

## What "smart" means for each feature

### Smart setbacks
Once the system has enough data (several heating cycles), it learns:
- How fast each room recovers from night/away setback (warm rate)
- How much setback the room can handle while still recovering in time
- Deeper setbacks for well-insulated rooms, shallower for poorly insulated ones

### Optimal start (dead-time)
The system tracks:
- **Dead time** — minutes between enabling heat and the room temperature starting to rise
- **Warm rate** — °C per hour once the room is actively warming
- These combine: `lead = dead_time + deficit/warm_rate + margin`
- Pre-heat starts exactly when needed — not earlier (wasting gas), not later (cold rooms)

### Auto-tune
The heating curve coefficient is adjusted based on whether rooms are actually reaching their targets:
- Rooms consistently too warm → coefficient decreases (lower flow)
- Rooms consistently too cold → coefficient increases (higher flow)
- Learning is slow and conservative to avoid oscillation
