# Calibration & setbacks

## Bootstrap calibration

One-click measurement that seeds the setback learner and dead-time tracker.

### How to calibrate

1. Make sure the room is **cold** (no heating for at least 30 min)
2. On the **Rooms** tab, click the **Calibrate** button (thermometer icon) on the zone card
3. The system heats at maximum for a measured period
4. It calculates:
   - **Warm rate** (°C/hour) — how fast the room heats up at full power
   - **Dead time** (minutes) — delay between enabling heat and the first temperature rise
5. These values are stored and used for:
   - Optimal-start pre-heat timing
   - Smart setback depth calculation
   - Health flag patience

### When to re-calibrate

- After insulation changes (new windows, added insulation)
- After changing radiators or heating system
- If warm rate seems wrong (rooms heat much faster/slower than before)
- First calibration gives the best head start — the system also learns from normal operation

### What calibration doesn't do

- Doesn't change your heating curve
- Doesn't override manual preset selections
- Doesn't affect the boiler — it just measures

## Dead-time learning

Tracks the delay between "heat requested" and "room temp starts rising."

### Sources

- **Calibration** — most accurate (measured in controlled conditions)
- **Normal operation** — inferred from setback→comfort transitions
- **Window detection** — can estimate dead time from slope analysis

### How it's used

```
lead = dead_time + deficit / warm_rate + margin
```

- `dead_time` — minutes before temp starts rising
- `deficit` — difference between current temp and target (e.g. 3 °C below)
- `warm_rate` — °C/hour during active heating
- `margin` — safety buffer (configurable)

The lead tells the system exactly when to start pre-heating so the room reaches target on time.

## Smart setbacks

Learned per-room night/away depth based on recovery speed.

### How it learns

1. During night/away setback, the system observes how the room cools
2. When it's time to recover, it measures how fast the room warms up
3. It calculates the maximum setback depth the room can recover from before the next comfort window
4. Better-insulated rooms get deeper setbacks (they recover faster)
5. Poorly insulated rooms get shallower setbacks (they need more time)

### Setback presets

| Preset | Typical depth | Use case |
|---|---|---|
| Night | 2–5 °C below comfort | Sleeping hours |
| Away | 3–8 °C below comfort | Out of house |
| Eco | 1–3 °C below comfort | Energy saving |

### Optimal start

Combines dead-time + warm-rate + setback depth to calculate exactly when to start:

```
How much do I need to warm? → deficit from setback to comfort
How fast can I warm?       → warm_rate (°C/h)
How long until I need it?  → time until comfort window
When to start?            → now + time_available - lead
```

- **Reactive pre-heat** runs when away/eco and the calculated lead already exceeds the time budget
- Learning **freezes during pre-heat** to avoid confusing pre-heat data with normal operation

### Learning freeze conditions

- During pre-heat (calculated lead active)
- During calibration (controlled measurement)
- When outdoor temp is unavailable (unreliable data)
