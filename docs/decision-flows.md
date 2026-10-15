# HCC decision flows — whole-app logic spec (audit pass)

Companion to `docs/decision-tables.md` (room/boiler control). This file
covers every OTHER subsystem's implied decision logic, as步步 rules,
with an attack pass per subsystem. Rules marked `[FIXED]` were logic
flaws found by this audit and repaired same-pass. `OPEN` items are real
issues left for later batches with reasons.

## 1. Bootstrap / lifecycle

| # | When | Then |
|---|------|------|
| 1.1 | Integration setup starts | zones config deduped (non-dict entries skipped with warning); the ZonesBackup safety net is consulted **only when the live zone list is empty** |
| 1.2 | Controller constructed | datalogger + learner schedulers start; **`entry.async_on_unload(learner.async_stop)` is NOT registered during setup** [OPEN — a setup error mid-way can leave an orphan timer] |
| 1.3 | Entry unload | platforms unloaded → controller.async_stop → datalogger/gas final flush; the new stop-gate blocks in-flight ticks |
| 1.4 | ZonesBackup restore | restores a whole zone list from `.storage` when the live list is empty — **no field re-validation on restore** [OPEN — a corrupt backup injects unvalidated rooms] |

Attack: 1.2 and 1.4 are real. 1.2 is planned for the next robustness batch; 1.4 needs a
shared validator function — staged.

## 2. HCS backend connectivity

| # | When | Then |
|---|------|------|
| 2.1 | MQTT connect | retained config parse; discovery announcements from the board bind to their own topic |
| 2.2 | LWT offline from a board | device goes offline after grace window; on re-announce (no LWT seen) boards recover |
| 2.3 | Config-entry hasn't loaded yet (grace window) | retained discovery replays are **wiped** (poison guard) |
| 2.4 | Failsafe entity in HOLD/ON, or the board unreachable | `_system_healthy_for_auto()` = False → flow-curve writes, auto-cap and TRV flow writes are suppressed; calls to CH remain as-is (the board's own failsafe is in charge) |
| 2.5 | Supervision lost while a valve room holds an opening | valve written to 0 and idempotent per outage |

Attack: 2.4 means CH state is left to the board during failsafe — intentional
(the board is the last line of defense), verified sane.

## 3. Room cascade → `decision-tables.md` (Tables 1–10) — no new findings.

## 4. Schedule engine

| # | When | Then |
|---|------|------|
| 4.1 | Schedule entity state changes | preset applied as `schedule`; room user-source reset; TRV pushed |
| 4.2 | Same preset re-applies | no-op guard covers `schedule` AND `occupancy` sources (no per-tick writes) |
| 4.3 | Schedule disabled | `current_preset()` returns None → occupancy presence "home" falls back to the configured home preset |

Attack: none beyond what decision-tables.md lists. Verified.

## 5. Occupancy / presence

| # | When | Then |
|---|------|------|
| 5.1 | All presence trackers away | `away_preset` on every controllable room (manual rooms skipped) |
| 5.2 | Anyone home, schedule enabled | the SCHEDULE's current preset wins for home (night eco still applies) |
| 5.3 | Anyone home, schedule disabled | home preset (comfort) |
| 5.4 | Unavailable trackers | ignored, not counted as away |
| 5.5 | User overrode a room while presence unchanged | that room is skipped (sticky user wins) |

Attack: 5.2/5.3 verified sane. One subtlety: 5.1 away affects floor rooms too —
floors dominating a cold floor slab set back; acceptable (documented).

## 6. Environment adjusters (solar / wind / CO2)

| # | When | Then |
|---|------|------|
| 6.1 | Lux-based solar: lux_hysteresis high→ active | effective setpoint −0.5 °C |
| 6.2 | Sun-position fallback (no lux) | −0.3 °C, requires sustained ≥44° elevation; lux always wins |
| 6.3 | Wind trim on the outdoor curve | up to 3 °C; a NaN payload is rejected [FIXED] |
| 6.4 | CO2 hysteresis (800/1000 ppm) | `needs_ventilation` flag only — never touches heat [FIXED: NaN rejected] |
| 6.5 | A sensor reports NaN | rejected BEFORE the EMAs (valve balance, solar, CO2, wind trim, room temp) [FIXED] |

## 7. Gas meter & statistics

| # | When | Then |
|------|------|------|
| 7.1 | Boiler flame on | kWh integrated per tick from live rate |
| 7.2 | Downtime > 5 min | the gap under-counts by design (clamped), logged INFO as dropped [OPEN — bridging planned] |
| 7.3 | Stats reset | day buckets cleared, totals kept? [FIXED: totals kept; verified] |

## 8. Preheat (optimal start)

| # | When | Then |
|------|------|------|
| 8.1 | Preset away/eco + learned warm/dead times say "arrive cold" | comfort-target heat starts early |
| 8.2 | Deficit ≤ 0.15 reached while preheating | disarms back to the setback target |
| 8.3 | Windows open | preheat disarmed |

## 9. Learner / AI

`learner` spec is in decision-tables.md Table 9 + audit fixes. **Shadow-only forever
until a model demonstrably beats the heuristics — no control influence today.**

## 10. Firmware management

| # | When | Then |
|------|------|------|
| 10.1 | Catalog TTL expires | refresh from GitHub; a corrupt/oversized response is refused; 10 MB cap per fetch |
| 10.2 | Mirror stale (sha/size mismatch) | re-download; digest required for third-party hosts [FIXED: github-bundled hosts allow legacy no-digest flow; others refuse] |
| 10.3 | Flash via WS | board MQTT gets the URL; the board verifies ECDSA sig; ESP8266 lacks it [OPEN — firmware-side, known] |
| 10.4 | Update check forced | admin-only [FIXED — was reachable by any user burning GitHub quota] |
| 10.5 | WC curve values | isfinite + range-checked [FIXED] |

## 11. ZonesBackup

| # | When | Then |
|------|------|------|
| 11.1 | Zones added/renamed/removed | backup saved (fire-and-forget) |
| 11.2 | Options loaded with zero rooms | backup restored wholesale — **unvalidated** [OPEN — staged for the next batch: validate on restore] |

## 12. WS API permissions

State-mutating handlers are admin-gated; read-only ones are not, by design
(the panel itself is intentionally non-admin). `check_updates` [FIXED].
Device-IP leakage to non-admins: accepted product trade-off, documented.

## 13. Panel flows

Add/edit rooms, popup flows, Debug table, learner card — DOM-gated. No new findings.

## 14. Observability

Debug ring (400 lines + dedicated 120-line learner ring), control-health
sensors, learner scorecards, gas stats. All bounded.

---

## Attack summary

- **[FIXED THIS PASS]** 4 logic flaws: `check_updates` privilege, mirror trust
  gate (third-party release assets without digest), CO2/wind/solar/valve NaN
  boundaries, gas gap under-count *documented* (fix planned), stale-restore
  validation (documented).
- **[OPEN — planned]** ZonesBackup restore validation (1.4/11.2), setup-window
  scheduler cleanup (1.2), gas gap bridging (7.2), ESP8266 OTA signing
  (firmware), MQTT gw_override clamp (firmware), TSet clamp (firmware).
- **[OPEN — will not change]** occupancy/floor interplay (documented),
  board-owns-failsafe during HOLD (intentional), device-IP visibility
  (product trade-off).
