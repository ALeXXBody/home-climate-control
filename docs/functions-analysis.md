# HCC — complete function inventory & analysis

Mission of this pass: analyze **every function of the app** — where it is
implemented, what it does, why, how good it is today, what it interacts
with, and where to improve it — then look at all of them together for
cross-mechanism optimizations. Gas saving is the core mission; this pass
covered control, learning, services and firmware in equal depth.

Status markers: ✅ solid · ⚠ needs attention · 🚧 improvement opportunity
(last section ranks every 🚧).

---

## A. Core control chain

### A1. Room climate entity + presets — `zone.py` ✅
WHAT/WHY: per-room climate entity for HA; holds target/preset/HVAC state;
`effective_setpoint()` combines room target, presets, learned recovery
offset, solar trim, preheat target. Manual temps reconcile with presets
(0.5-grid match auto-selects the preset; any other value drops the preset
and sticks as user). TRV setpoints read back in both directions.
PARAMS: DEFAULT_ZONE_SETPOINT, zone min/max 5-30 °C, grid 0.5.
STATUS: post-audit, solid. OPPORTUNITY: 🚧 manual-temp grid dead-zone
(documented) — no fix possible, TRVs own it.

### A2. PID + demand — `zone.py` ⚠
WHAT: clamped deficit/3 °C → demand → PID nudges flow ↑ for dragging rooms.
WHY: proportional comfort signal instead of on/off.
⚠ OPPORTUNITY: `demand_level()` recomputes `_update_preheat()` as a side
effect; heavy call sites; moving the preheat arm to a fixed tick would be
one less Who-knows-what (audit noted; not yet fixed).

### A3. Heating curve (weather compensation) — `heating_curve.py` ✅
WHAT: `flow = sp + coeff × load × 20 °C`; load normalized to design
outdoor → coeff 1.0 = full design load at design temp.
WHY: The single biggest condensing-boiler lever: colder weather → warmer
water, milder → colder; keeps return temps in the condensing band.
PARAMS: coeff (auto-tuned, see A16), min/max flow from settings,
design outdoor −10 °C default.
OPPORTUNITY: 🚧 design-outdoor is a flat constant; a config option (city
climate) would let frosty villages vs. mild coasts run the SAME program
correctly without manual coeff fiddling.

### A4. Flow setpoint & CH gating — `central.py` + `cycleguard.py` ✅
WHAT: flow_for_outdoor + worst PID nudge (non-floor rooms only); CycleGuard
enforces burn minimums and adaptive rest windows; dutycycle PWMs the burner
when required mod < boiler min (period = min_on/fraction with 600/600 s
floors); `demanding` rooms decide.
WHY: short cycles waste gas (purge + standby losses); min-mod drives
condensing efficiency.
STATUS: 🔀 cross-checks verified: duty min_on (600 s) ≥ cycleguard hard
min-on (240 s); duty OFF ≥ rest window → no fight. ✅
🚧 OPPORTUNITY (medium): duty cycle's `DEMAND_TO_MOD_PCT = 100` treats all
rooms uniform — a house whose rooms have `radiator_kw` set could map demand
to required modulation by kW instead of "1 room = 100 %". First houses that
fill kW will get a better PWM duty; currently the map is a coarse estimate.

### A5. Valve-direct loop — `zone.py` ✅
WHAT: demand % → `number.set_value` writes with hysteresis, 600 s rate
limit, close-on window/OFF/supervision-loss, anti-stick weekly sweep.
OPPORTUNITY: 🚧 the sweep is fire-and-forget (not tied to the entity
lifetime); a reload mid-sweep leaves a stale writer against the rebuilt
entity. Small fix; pending.

### A6. Floor mode — `zone.py` `floor_tick` 🚧 beta
WHAT/WHY: deep hysteresis on the room + a 45 °C loop-flow cap + surface cap
+ pump interlock; mixer from the outdoor curve or 40 °C closed loop.
STATUS: shipped, beta. INTERACTIONS: floor excluded from radiator curve AND
from the auto-tune error (this pass) — both were real interaction bugs that
the function-by-function pass found. definite entry into ⚠→✅ once a pilot
house has run real winter data.

### A7. TRV pushes/readback — `zone.py` ✅
WHAT: downward-always pushes, upward half-grid suppression, echo+clamp
absorption, bidirectional adoption of user-changed targets.
OPPORTUNITY: 🚧 external co-writers (vendor apps, other HA automations) are
indistinguishable from humans — by design, last-writer-wins per tick. Fine;
documented.

### A8. Window detection — `window_detect.py` ✅
WHAT: cliff (0.35 °C/8 min) + sustained-escape (0.2 °C over 30 min while
heating pushes) + setpoint-drop suppression for schedule changes.
🚧 OPEN: escape pauses have no hard cap while the room keeps falling —
the docstring promises one; misdiagnosis self-reinforces (heat paused →
room keeps falling → stays paused). Guarded by setpoint checks, but a
2-3 h hard cap for escape trips is the safe compromise. HIGH priority.

### A9. Solar/wind/CO2 adjusters — `solar.py`/`windtrim.py`/`co2.py` ✅
- solar: comfort trim −0.5 (lux) / −0.3 (sun position), EMA+hysteresis.
- wind: bounded outdoor trim `0.25·wind^0.9` — keeps the curve coefficient
  honest on windy days (systemic saving: no inflated learned coeff).
- CO2: ventilation flag only by design.
OPPORTUNITY: 🚧 (small) CO2 could raise already-armed preheats' priority
("ventilate THEN preheat"), but ventilation is a human task — current design
is right.

### A10. Preheat / optimal start — `preheat.py` ✅
WHAT: room-learned warm rate + dead time → lead time to comfort; enters at
deficit ≥ 0.4 °C during a setback window; margin = LEAD_MARGIN_S.
WHY: arrive on time with the minimum burn; the biggest cheap saving for
schedule houses.
🚧 currently radiator rooms only (no floor) — floor preheat is a natural
next step when floor P0 pilot exists (lead times would be hours, feasible
with the learner).

### A11. Learned setbacks + dead-time — `setback.py` + `deadtime.py` ✅
WHAT: per-room recovery rate measured every real setback→recovery cycle;
depth = rate × 1.0 h window (clamped −1..−5 °C); slow rooms go shallow;
snappy rooms go deep — biggest honest saving; preheat guarantees arrival.
dead-time tracks CH start → room movement delay; feeds preheat.
OPPORTUNITY: 🚧 (medium) the learned depth ignores the INSULATION score
(insulation is display-only today, see A17). Feed `k` into the depth clamp:
a k=heavy house should slightly deepen its setback (it recovers slower but
holds deeper cold longer), earning extra savings margin — worth a design note,
not a quick patch.

### A12. Occupancy / schedule / global mode — `occupancy.py`/`schedule.py`/`select.py` ✅
Away relieves every controllable room; home hands control to the schedule;
sticky user beats occupancy between presence changes; night eco from the
schedule still wins at home when enabled. Solid.

### A13. Manual/alive guardrails — ✅
Manual rooms are pure observers; failsafe HOLD blocks all writes; NaN
payloads rejected at every sensor boundary; temperature staleness is
detected after 90 min (no "frozen sensor" pinning demand).

---

## B. Learning & modeling

### B14. Auto-tune curve coefficient — `autotune.py` ✅ + this-pass fix
WHAT/WHY: watches aggregate room error vs the curve; sustained cold → coeff
up; overshoot (offset = wasted gas) → down; deadband ±0.2; steps ≤0.1; ≥1 h
cool-down; weekly anti-railing walk keeps a parked coeff honest.
FIX THIS PASS: the error average used to include floor rooms — their
structural deficits (loop capped) would have ratcheted the radiator curve
(and radiator gas) up every floor-heavy day. Excluded.
OPPORTUNITY: 🚧 the aggregate error is a simple mean — weighting rooms by
`radiator_kw` would stop a small bathroom from steering the whole house's
curve. Candidate for the next batch.

### B15. Room calibration — `calibrate.py` ✅
On-demand boosted measurement giving the setback learner day-0 data.
Small, does exactly one job well.

### B16. Insulation scorer — `insulation.py` ⚠ display-only today
WHAT/WHY: k-loss factor per room from cooling stretches (setback learner
phase gives the "heater-off ground truth").
TRUTH: score was designed to help decide per-room curve offsets or setback
depths, but currently only feeds the training row and the panel. Enjoyment
opportunity: integrate into A11 (setback depth clamp) — documented in the
next batch.

### B17. Balancing (TRV auto-cap) — `balancing.py` ✅ behind gating
WHAT/WHY: rooms whose valve sits ≈ open with a satisfied room waste pipe
capacity; a suggested `max-opening cap` frees headroom for starved rooms →
less forced full-flow. Auto-cap persists per-room cooldown and re-asserts.
OPPORTUNITY: 🚧 suggested_cap currently written once per cooldown expiry;
a second pass comparing post-cap valve behavior would verify the cap is
right and adapt downward — worth doing after A5's task-lifetime fix.

### B18. Learner / AI shadow models — `learner.py` ✅
Weekly local fit per room over the house's own rows (10-min windows,
heating-weighted, rollback on a worse fit); predicts ΔT/10min beside reality
in the debug ring; coverage gates (7 days, ≥2k heated minutes, ≥8 °C outdoor
spread) block new installs' garbage fits. Shadow-only until it BEATS the
heuristics on the scorecards. All correct per design; next step = the
promotion criteria implementation (gate on skill > 0 with n ≥ floor).

### B19. Training data logger — `datalogger.py` ✅
One row/min, monthly files outside `custom_components/` (survives updates);
flushed every 5 min/500 rows; meta now atomic.

---

## C. Accounting

### C20. Gas meter — `gasmeter.py` ✅ (post 1.18.5)
Integrates live burner rate; persists last_t; short restarts bridge,
longer downtime is logged as not counted (deliberate: an unknown gap must
not be billed at one rate).
OPPORTUNITY: 🚧 `MAX_DT_S = 300` cap: the meter could optionally SPLIT the
gap at the homeowner value (e.g., billing only when a heating schedule
would have been active) — but that is a guess; current conservative math is
the honest one. Keep.

### C21. Statistics — `stats.py` ✅ daily buckets, 30-day trend, per-day gas
+ price; reset is admin-gated.

---

## D. Safety & health

### D22. Health flags — `health.py` ✅ DIAGNOSTIC-ONLY design decision.
struggling (full-flow long deficit) + blocked-airflow (TRV satisfied, room
starved) both display-only; they never pause heat. Right call: these
detect PHYSICAL problems a human must fix.

### D23. Failsafe interplay — ✅ deliberate: when the HCS failsafe is in
HOLD/ON, the app writes nothing (the board's failsafe has command).

### D24. NaN/staleness guards — ✅ at every boundary post-audits.

---

## E. Services & infrastructure

### E25. Backend connectivity (HCS MQTT) — `firmware_manager.py`/`mqtt_bridge` ✅
grace window wipes replayed discovery; LWT/bookkeeping; supervision gates.

### E26. Firmware manager — catalog/mirror/signing ✅ post-1.18.4/5
Third-party assets without digest refused; github-hosted legacy kept;
10 MB per-fetch cap; ECDSA verified on ESP32 (ESP8266 gap remains, HCS lane).

### E27. Update checker — Store-stored token, header-only use ✅
`check_updates` admin-gated (was a quota leak).

### E28. WS API — `websocket_api.py` ✅ all mutators admin-gated (post-audit);
read-only surface intentionally open for the non-admin panel.

### E29. Panel — `home-climate-panel.js` ✅ post-audit: escaping swept,
popup/flows DOM-gated.

### E30. ZonesBackup — ✅ now sanitized on restore (post-1.18.5).

### E31. Debug/observability — debug ring + learner ring + scorecards ✅
bounded; every feature exposes its own state (learner card, gas stats,
flow-cap card…).

---

# Cross-mechanism synthesis (all functions together)

## Interaction map (the load-bearing rivets)
```
weather curve (A3) ←─ coeff (B14) ←─ room error (excl. floor; B14)
       ↑ outdoor+wind (A9)                     ↑ manual/preset sp (A1)
   flow setpoint (A4) ── PID worst-room (A2) ── TRVs/rooms (A7/A5/A6)
              │ duty/cycle guard
   gas meter (C20) ← boiler ← HCS board
   preheat (A10) ←── dead-time (A11) ←── setback learning (A11)
   balancing (B17) ──→ valve caps ──→ room mix ──→ demand mix
   learner (B18) ←── datalogger (B19) ←── everything
```
No cycles; every arrow has a single writer — verified on this pass.

## Ranked improvement backlog (🚧 from above)

| # | Opportunity | Where | Impact | Effort |
|---|---|---|---|---|
| 1 | Escape-pause hard cap (2–3 h) | window_detect | HIGH (comfort safety) | S |
| 2 | Autotune error weighted by radiator_kw | central/autotune | MED-HIGH (gas) | S |
| 3 | Duty mod from actual kW when rooms have radiator_kw | dutycycle | MED-HIGH (gas, cold snaps) | M |
| 4 | Floor preheat (hours lead) | preheat/floor | MED (comfort for floor houses) | M |
| 5 | Feed insulation k into setback depth clamp | setback | MED (savings) | M |
| 6 | Post-cap verification pass for balancing | balancing | MED (reclaims headroom honestly) | M |
| 7 | Design-outdoor as a config option | heating_curve | MED (correctness across climates) | S |
| 8 | Exercise task bound to entity lifetime | zone | LOW-MED (safety) | S |
| 9 | Manual-grid dead zone通透 | panel/docs | LOW (documented) | — |
| 10 | CO2-ventilate-then-preheat note | preheat | LOW | — |

## What works better than designed
- Setback learning + preheat combo (A10+A11) is the app's most elegant
  saving: deep where free, shallow where costly, always on time.
- The condensing pull-down (condense.py) is not in this inventory before:
  it pulls flow BELOW the curve target while return exceeds ~54 °C (dew
  point) with no large room deficit — that's peak-condensing optimization,
  active every mild day in this house.
- Window detection's triple (physical + cliff + intro escape) covers open
  windows finally (guest-bedroom-style cases) vs the old 45-min cone.
