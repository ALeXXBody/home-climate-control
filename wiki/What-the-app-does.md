# What the app does

Home Climate Control replaces your boiler's own controller with a smarter one. Here is the complete picture of what it manages and how each layer contributes to "warm + less gas".

## The control loop (runs every 60 seconds)

1. Read every room's temperature and its TRV's target.
2. Decide which rooms actually want heat (demand = how far below target).
3. If any room wants heat → turn the boiler **CH on**; otherwise leave it off.
4. Compute the boiler **flow temperature** from the **weather-compensation curve**.
5. Apply gas-saving corrections (condensing, flow cap, PID).
6. Send the flow setpoint to the board; the board applies it to the boiler.

Everything below tweaks one of those steps.

## 1. Weather compensation

The core: the colder it is outside, the hotter the radiators need to be.

```
flow = room_setpoint + coefficient × (setpoint − outdoor) / (setpoint − design_outdoor) × 20
```

This is the *curve*. You set the **coefficient** (how steeply flow rises as it gets colder) and the **design outdoor** (the coldest you design for). Rooms that need more flow get it automatically on cold days, and the boiler runs cooler on mild days.

## 2. Per-room TRV demand

Most boilers heat the *whole house* when *any* thermostat calls. HCC reads each TRV individually and only aggregates the rooms that are actually below target — so you don't heat rooms that are already warm.

## 3. Condensing pull-down

A condensing boiler only reaches its high efficiency when the **return** temperature is below the flue-gas dew point (≈54 °C). When the return creeps above that, HCC **lowers the flow setpoint** to pull the return back down — reclaiming efficiency that a fixed curve throws away.

## 4. Auto-cap max flow

If the return stays hot for a sustained window (e.g. radiators are oversized), HCC trims the **maximum** flow temperature downward so the system stops overheating the return. (Part of **Auto-Optimize**.)

## 5. Duty-cycle (low-load PWM)

Below the boiler's **minimum modulation** (e.g. 20%), most boilers short-cycle on/off, wasting gas and wear. HCC instead turns the burner on/off in **long slices** (default 10 min) at the required fraction — like a PWM — so the flame runs at its efficient minimum instead of cycling.

## 6. Cycle-guard (anti-short-cycling)

Enforces a **minimum burn time** (4 min) and an **adaptive rest time** between starts, so the boiler is never hammered with rapid on/off cycles.

## 7. Smart setbacks (learned)

Instead of a fixed "away = −4 °C", HCC **measures how fast each room recovers** and sizes that room's setback depth so it can warm back up in time. Slow, leaky rooms get shallow setbacks; fast rooms get deep (bigger saving). Needs a few away/eco cycles to learn.

## 8. Optimal start (pre-heat)

Using the measured recovery speed + radiator **dead-time**, HCC starts heating *before* your comfort time so the room is already warm when you need it — no cold-start catch-up burn.

## 9. Dead-time estimation

Measures the lag between "boiler fires" and "room temperature starts to move" (the transport delay of the radiator). Fed into optimal-start and setback depth.

## 10. Curve auto-tune

Over time, HCC nudges the curve coefficient to match your house: if rooms chronically undershoot, it steepens the curve; if they overshoot, it flattens it. (Part of **Auto-Optimize**.)

## 11. Wind trim

On windy days, infiltration increases heat loss. HCC trims the curve's outdoor input by the wind speed (needs a weather entity with `wind_speed`).

## 12. Insulation & balancing (Tier 3 / Tier 4)

- **Insulation score** — a weather-normalized heat-loss factor per room.
- **TRV balancing** — automatically re-balances valve limits so rooms warm up evenly. (Opt-in.)

## 13. Statistics & gas meter

Daily gas (kWh + cost), heat demand, burner hours, and a gas-vs-outdoor scatter — so you can *see* the savings. Optionally calibrated to your real gas meter.

---

Next: [Installation](Installation) → [Configuration](Configuration) → [Using the panel](Using-the-panel).
