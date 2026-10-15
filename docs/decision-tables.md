# HCC control logic — decision tables (the "if room is cold, then what?" spec)

Every rule below is extracted from the actual code (verified against zone.py,
central.py, window_detect.py, solar.py, health.py, learner.py, the window
detector and the floor loop). Order matters: earlier rules win.

## Legend

`cur` = room temperature (external sensor; falls back to the TRV's internal
when no external sensor is configured). `sp` = effective setpoint (see
Table 3). `demand` = 0..1 = how far below setpoint the room is, clamped to
3 °C. `TRV` = any smart TRV cloud entity configured for the room.

---

## Table 1 — Per-room state machine at each 60 s control tick

| # | When (highest priority first) | Then |
|---|---|---|
| 1 | HVAC is `off` | room writes demand 0; a valve-direct loop is **driven to 0 %**; a floor loop is turned off; nothing else. |
| 2 | Window open (physical sensor, or slope/careful-escape suspicion) | room paused: demand 0, ignored by the CH calculation, no preheat; a valve-direct loop is written to 0 %; floor loop turns off; TRV target is NOT pushed down (the room's local control stays) |
| 3 | Heat control is `manual` | HCC never touches the TRV; room never counts toward wrapper demand. Pure observer. |
| 4 | Preset `away`/`eco` active and the room had already reached its comfort target | room demand = how far below the preset temp it is (NOT below the original comfort target) |
| 5 | Preheat armed (away/eco, recovery window risks arriving cold) | room targets the COMFORT setpoint now; demand computed against it |
| 6 | Manual temperature accepted (0.5-grid match to a preset, or fully distinct) | that target wins; sticky "user" until the schedule entity advances |
| 7 | Room mode `floor` | floor loop logic (Table 6) — no TRV writes |
| 8 | Any other case | demand = (sp − cur) clamped to 0..3 °C. This drives: CH on/off, boiler flow setpoint over the outdoor curve, valve-direct loop writes, TRV setpoint (Table 5 conditionally). |

## Table 2 — Boiler (CH) decision, once per tick (house-wide)

| # | When | CH is |
|---|---|---|
| 1 | total demand > 0 and duty cycle says fire | ON |
| 2 | total demand > 0, load below min modulation (low demand) | duty cycle pulses ON in a min-on/off window |
| 3 | total demand > 0 but the cycle rate is too high | ON skipped until the cooldown (CycleGuard rest interval passes) |
| 4 | total demand = 0 | OFF; if ON, it finishes the minimum burn at low fire |
| 5 | Boiler communication fails (MQTT/OT down) | OFF forced — a dead gateway must never leave heat running unmonitored |

## Table 3 — Effective setpoint selection (per room per tick)

| # | When | effective setpoint is |
|---|---|---|
| 1 | HVAC off | n/a (duty stops) |
| 2 | preset `away`/`eco` and preheat NOT armed | preset temperature, possibly **raised** by the learned recovery offset (never lower) |
| 3 | preset `away`/`eco` and preheat ARMED | comfort setpoint (the target the room should reach before the window ends) |
| 4 | preset `comfort`/`boost` | that preset's temperature (absolutely defined, no learned offset) |
| 5 | preset none | the room's own target |
| 6 | solar-gain active (bright sun in the room) | −0.5 °C (lux) or −0.3 °C (sun position proxy); never in away/eco |

## Table 4 — Boiler flow setpoint (water temperature)

| # | When | flow target is |
|---|---|---|
| 1 | House demand exists | outdoor curve: colder outside → hotter water; plus the worst PID nudge from any dragging room; clamped to [min_flow, max_flow] from the settings |
| 2 | Every demanding room is a FLOOR room | the target is the floor loop cap (45 °C + the learned PID headroom only) |
| 3 | No outdoor reading | the curve runs at a mild fallback (0 °C), warn once |
| 4 | Demand vanished mid-burn | finish the minimum burn at the previous (low) setpoint, then stop |

## Table 5 — TRV setpoint writes (smart rooms)

| # | When | Then |
|---|---|---|
| 1 | Target differs by MORE than half a grid step (e.g. 0.5 °C grid on most TRVs) | write it to the TRV |
| 2 | Target differs by less than the TRV's own grid step upward | skip the write (silent) — this is the "no-op suppression" that saves battery |
| 3 | Target LOWER than what the TRV holds — even by a fraction | ALWAYS write (a downward suppression once burned gas as a bug) |
| 4 | The user changes the temp on the TRV itself | HCC adopts the value; if it grid-matches a preset's temp, the preset is selected; otherwise it becomes the manual user target (same rules as the panel) |
| 5 | HCC pushes a target, the TRV echoes it back | absorbed silently (that's the push echo) |
| 6 | HCC pushes a target, the TRV clamps it to its own min/max | absorbed silently (the clamp echo): the TRV's own limit rules get their say |


## Table 6 — Floor room (underfloor heating — beta)

| # | When | Then |
|---|---|---|
| 1 | HVAC off / no temperature reading / window open / pump off / slab above surface cap / loop flow above 45 °C | loop forced OFF, regardless of anything else |
| 2 | Room below the target by more than 0.25 °C | loop ON (after the 5-min re-open dwell) |
| 3 | Room above the target by more than 0.35 °C | loop off — closing is never dwell-limited |
| 4 | Surface temperature within 1 °C below the cap | hold current state, it recovers as the floor passes the cap band down |
| 5 | Mixer present | low flow target: the outdoor curve (from outdoor) OR a closed loop around 40 °C loop flow if a flow sensor exists |

## Table 7 — Window detection (rooms without contact sensors)

| # | When | Then |
|---|---|---|
| 1 | Temp drops ≥ 0.35 °C within 8 min | suspected open window: pause per Table 1 rule 2 |
| 2 | Schedule/manual setpoint dropped within the last 30 min | the detector is BLIND — a setback cooling tail is NOT a window; heating follows the new target |
| 3 | Slowly draining room at/near target, heating pushing, over 30 min | suspected "sustained heat escape" (open window, days): pause |
| 4 | Pause reached 45 min OR the room stabilizes/rises | resume normal heat (an escape-reason pause continues only while the room keeps falling); a remote pause lifts once the room returns to normal |
| 5 | Sensor lies ("nan") | boundary filter rejects it → NOT a window, heating continues |

## Table 8 — Per-trubble flags (diagnostic only; they do NOT change control)

| # | When | Then |
|---|---|---|
| 1 | Heating pushes at full flow while the room stays ≥ 0.8 °C short | room flagged **struggling** (health screen) — never pauses heat |
| 2 | Heating pushes while the TRV head already reads satisfied and the room stays ≥ 1 °C short | room flagged **blocked airflow** (TRV screen) — never pauses heat |
| 3 | Either flag clears | touched when the room meets its target, the heat demand stops, or the TRV calls for heat again |

## Table 9 — AI/self-learning (shadow mode)

| # | When | Then |
|---|---|---|
| 1 | Coverage gates pass (≥7 days; ≥2,000 heated minutes; ≥8 °C outdoor spread) | weekly fit → room model |
| 2 | A fit is worse than the stored one | keep the previous model (rollback) |
| 3 | The model predicts | logged next to reality by the control loop — never influence control |

## Table 10 — The schedule / occupancy / central-mode ladder

| # | When | Then |
|---|---|---|
| 1 | Schedule entity advances | preset applied with the sticky source `schedule`; TRV pushed |
| 2 | Presence (tracker) goes "away"/"home" | away / comfort preset applied; occupancy owns the preset until presence changes back |
| 3 | Panel's global heating mode | comfort/eco/away/boost broadcast to all controllable rooms; `auto` returns schedule control per-room |
| 4 | All earlier rules applied | TRV target writes (Table 5), valve writes (1), floor loop (6), CH gating (2) |

---

# Attack: holes and contradictions found against these tables

1. **[fixed in v1.18.0–3] rules 7/8 room-temperature modes invalid order**: 
   floor-mode rooms that had `heat_control=floor` used to fall to smart silently — 
   fixed by the validation tuple. Test protects it.

2. **[fixed] Rule 5 row 5 (write echo) allowed a clamp echo to redefine the user's intent.**

3. **[still open, MEDIUM] TRV readback adoption with external writers**: any second app
   that writes the TRV (e.g. a vendor app or schedule) becomes indistinguishable from a
   human touch. The current design makes HCC the least-invasive vice ruler (last writer
   wins per tick) — acceptable, but documented as a real ambiguity: HCC throws its
   schedule target away instead of conflicting. Keep on the panel as-is, but logged.

4. **[fixed] Table 4 row 2 was missing**: floor rooms used to push the radiator curve
   to 48 °C — the audit drove the exclusion.

5. **[MEDIUM, open] Table 8 rules never gate anything, by design.** If you want the
   struggling flag to also shed the demand path automatically (bad idea) it would need
   an explicit settings knob; but the design says diagnostics stay diagnostics.

6. **[MEDIUM, open] Demand-only (no outdoor sensor) heat-parity**: a house without an
   outdoor sensor drives learner windows with a 0.25× weight floor; the coverage
   statistics still count them as if full. The AI side is where this mis-wtih sits.
   Not a control risk (it's shadow-only), but the coverage math should be done on
   heat-weighted minutes.

7. **[LOW, open] Table 7 row 3 recovery nuance**: the escape pause continues only
   while the room is falling — a *paused heating but the room removed from falling by
   design* (permanently marginal radiator)不停地 latched. This is the one unresolved
   state where a misdetected "escape" can keep a room cold for hours. Mitigated by
   setpoint guards and the 45-min cap for the CLIFF trigger, but escape keeps a
   longer tail. Needs a network reviewer's eye.

8. **[LOW, open] TRV grid deadzone**: Rule 5 row 2's suppression means a *manual
   push of exactly ±0.3–0.45 °C below the TRV's held target* is a no-op — intentional
   (battery-friendly), but a user nudging the panel by one 0.1 step may see no change
   in the TRV. The panel exposes the room target correctly; only the physical TRV
   lags until the next ≥0.5 change. Not a fix a code change can make (it's the TRV's
   grid), documented here for completeness.

Where the spec says "fixed already", the fix landed in v1.18.0–v1.18.3 with tests.

## The one-liner, in your format

> **If the room temperature drops below the set temperature**, then (in order):
> the room demands heat; the boiler turns on with a flow temperature derived
> from the outdoor curve; the TRV is pushed the new target (if it crosses a
> half-grid step); the valve/floor loop opens per its own hysteresis; preheat
> may intercede if a setback risks being late; solar trim may subtract 0.5 °C;
> window/state guards can pause any of it; health flags stay diagnostic-only.
>
> **Else** (room at/above set): TRV writes are suppressed (no-op), the loop
> closes, the floor loop shuts, CH goes off after its minimum burn, and the
> window/solar/AI checks watch without acting.
