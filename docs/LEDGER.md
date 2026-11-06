# Project ledger — Home Climate Control & Home Climate System

A single historical record of both repositories from the first commit to the
present: what shipped, when, why, and what was decided along the way. This is
a reference document, not a plan. Open work lives in
`docs/HCC-HCS-COMPACT-2026-10.md`; current behaviour lives in the code.

Compiled 2026-11-06 from the Git history of both repositories.

## 1. Scope and method

| Item | Value |
|---|---|
| HCC repo | `ALeXXBody/home-climate-control` (integration + sidebar panel) |
| HCS repo | `ALeXXBody/home-climate-system` (firmware + hardware) |
| HCC history | 367 commits, 172 tags, first commit 2026-08-22, last 2026-11-04 |
| HCS history | 133 commits, 65 tags, first commit 2026-08-22, last 2026-11-02 |
| HCC head | `v1.32.0` → `2de5b06` |
| HCS head | `v1.5.32` → `a80a697` |

Every row below is taken from a tag or a commit in one of the two repos. Where
the release note subject was terse (just the version number), the row records
the commit subject instead — that is why some rows are short and some carry a
sentence. Dates are tag creation dates in local time.

Method: `git for-each-ref refs/tags --sort=creatordate` for the release order,
`git log --reverse` for the pre-tag history, `git show --stat` for what each
release actually touched, and the repository docs for intent. Every claim in
the branding and drift sections was checked against the tree on 2026-11-06.

## 2. Products and naming

The project started as one repository called *Home Climate System*. On
2026-08-22 it was split by role and renamed (commit `f87416d`):

| Name | What it is | Repo |
|---|---|---|
| **Home Climate Control (HCC)** | Home Assistant custom integration (HACS) plus sidebar panel: rooms, schedules, weather compensation, learning, statistics, boiler gateway supervision | `home-climate-control` |
| **Home Climate System (HCS)** | ESP32/ESP8266 firmware and DIY hardware: the OpenTherm boiler gateway the integration drives | `home-climate-system` |

The rule that settled the naming: **Control is the software, System is the
metal.** The integration never contains firmware logic, and the firmware never
contains room logic. HCC speaks to the boiler only through an HCS board over
MQTT (and, since v1.27.0, over the board's own HTTP portal as the primary
telemetry path).

## 3. Timeline at a glance

### HCC phases

| Phase | Dates | Theme |
|---|---|---|
| Pre-tag | 2026-08-22 | Naming, architecture, MVP skeleton, tests, sidebar panel, demo backend, first firmware catalog (32 commits) |
| v1.0.x | 2026-08-23 – 08-24 | First public line: audit fixes, rooms model, branding, firmware page, OTA mirror, first gas-saving features |
| v1.1.x | 2026-08-24 | Second audit, per-room learning: window detection, dead time, health flags, insulation score |
| v1.2 – v1.4 | 2026-08-24 – 08-26 | House model (floors, heater control), room CRUD, Tier 0/1 control: optimal start, duty cycling, condensing, ΔT gas, occupancy |
| v1.5 – v1.7 | 2026-08-27 – 09-02 | Wind compensation, editable Settings, Tier 3/4 (solar trim, CO2, balancing), Diagnostics UI, OTA/mirror hardening |
| v1.8 – v1.14 | 2026-09-20 | Auto-Optimize gates, platform-crash fixes, humidity, Statistics, unload/reload correctness |
| v1.15.x | 2026-09-20 – 10-03 | Floor plan, stats charts, CH self-heal, security hardening batch, signed OTA mirror, Debug screen, valve-direct mode |
| v1.16 – v1.19 | 2026-10-03 – 10-15 | Closing-degree valves, self-learning surfaces, audits, HA 2026.10 compatibility, bidirectional TRV sync, decision-flow spec |
| v1.20 – v1.23 | 2026-10-15 – 10-30 | CI resurrection, pyflakes gate, tag/version gate, keep-alive feed, honest compatibility floor, per-node diagnostics |
| v1.24 – v1.32 | 2026-10-31 – 11-04 | Radiator watts, MQTT-deafness recovery, pull-based OTA, HTTP-primary telemetry, uptime dial, one-board binding, Device card, batteries |

### HCS phases

| Phase | Dates | Theme |
|---|---|---|
| Pre-tag | 2026-08-22 | Firmware/hardware scaffold, OT master, portal, weather-comp curve, CI, gateway core (23 commits) |
| v0.3 – v0.9 | 2026-08-22 – 08-23 | Gateway role and routing, 1-Wire, boiler diagnostics, pressure/DHW, failsafe, member-ID |
| v1.0 – v1.2 | 2026-08-23 – 08-24 | First stable firmware, 1-Wire auto-detect, OTA progress, MQTT settings sync |
| v1.3 | 2026-08-24 – 08-25 | OTGW compatibility purge, power-health telemetry, on-board OT console, bugfix batch |
| v1.4 | 2026-08-26 – 08-27 | ESP32-C3 brick/recovery saga, recovery image, standalone recovery project |
| v1.5.0 – v1.5.20 | 2026-08-27 – 09-24 | Gateway self-heal, CSRF + auth flow, MAC-derived password, ECDSA-signed OTA, boot health latch |
| v1.5.22 – v1.5.26 | 2026-10-15 – 10-16 | Toolchain pinning, ESP8266 signed OTA, OT FIFO, image-size budget, learned CH ceiling |
| v1.5.27 – v1.5.32 | 2026-11-02 | Zombie-MQTT guard, session rebind, portal MQTT truth, pull self-update, missed-read fallback |

## 4. HCC release ledger

Semver tags only, in release order. `v1.4.6-dev2/3/4` are the three non-semver
tags and appear in their place.

### 4.1 v1.0.x — first public line (2026-08-23 – 08-24)

| Version | Change |
|---|---|
| v1.0.0 | Security and stability audit fixes; official branding; tested-hardware README |
| v1.0.1 | Native HCS setup step, import-crash fixes, `brand/` folder, update-checker race fix |
| v1.0.2 | Bug fixes |
| v1.0.3 | Missing `BACKEND_HCS` import crashed every setup entry (regression-tested); pyflakes clean |
| v1.0.4 | Flash reliability, catalog dropdown, native update entity, notice polish |
| v1.0.5 | Bug fixes |
| v1.0.6 | Bug fixes |
| v1.0.7 | Rooms model: TRV + optional wall sensor + window/door sensors; HCS is boiler gateway only |
| v1.0.8 | Rooms model + audit fixes |
| v1.0.9 | Stop HA state/notification spam after Install/Update |
| v1.0.10 | Normalise `brand/` logo sizes to spec (1× ≤ 256, 2× = 512) |
| v1.0.11 | Firmware page shows only online boards; prune stale devices (10 min TTL) |
| v1.0.12 | Real board photos per model; catalog card layout; model names in the dropdown |
| v1.0.13 | Photos only in the catalog card; LWT-based online tracking kills ghost devices |
| v1.0.14 | Update entity uses an origin-relative cache-busted brand icon URL |
| v1.0.15 | Startup grace window wipes retained discovery/availability blobs; per-device up-to-date pill |
| v1.0.16 | GitHub-token box appears only when actually rate-limited |
| v1.0.17 | GitHub-token UI removed entirely |
| v1.0.18 | Control-first mission statement; firmware tab speaks "boiler gateway" |
| v1.0.19 | Self-tuning heating curve: comfort-driven coefficient learning |
| v1.0.20 | CycleGuard: adaptive burner rest window + minimum-on floor |
| v1.0.21 | Smart setbacks: learn per-room recovery speed |
| v1.0.22 | Estimated gas accounting from boiler telemetry |
| v1.0.23 | Custom 1-Wire probes as HA entities |
| v1.0.24 | Dynamic firmware catalog: pill tracks GitHub releases |
| v1.0.25 | OTA progress bar + failure notifications |
| v1.0.26 | Self-refreshing OTA LAN mirror (stale-image fix) |
| v1.0.27 | sha256-verified OTA mirror freshness |
| v1.0.28 | Board settings card: two-way sync with ESP boards |
| v1.0.29 | Board tab: two-way replica of the ESP Control page |
| v1.0.30 | Hand boards LAN-reachable OTA URLs (fix code −104) |
| v1.0.31 | Panel footer shows the running integration version |
| v1.0.32 | OTA mirror survives WS-triggered flashes (no request context) |
| v1.0.33 | Resolve successful OTA via post-reboot status publish |

### 4.2 v1.1.x — audit and per-room learning (2026-08-24)

| Version | Change |
|---|---|
| v1.1.0 | Security + stability audit fixes; panel logo |
| v1.1.1 | OTA success detection for silent-state boards |
| v1.1.2 | Version line continues on 1.1.x |
| v1.1.3 | Slope-based open-window detection for rooms without contact sensors |
| v1.1.4 | Per-room dead-time estimation from normal operation |
| v1.1.5 | Radiator health flags |
| v1.1.6 | Per-room insulation score from weather-normalised cool-downs |
| v1.1.7 | Board removal, header boiler alert, persistent training-data log |
| v1.1.8 | OTGW references purged — HCS-native only |
| v1.1.9 | Editable room names + removable room cards |

### 4.3 v1.2 – v1.4 — house model and Tier 0/1 (2026-08-24 – 08-26)

| Version | Change |
|---|---|
| v1.2.0 | House model: floors + heater-control types per room |
| v1.2.1 | Always-on boiler link pill in the app header |
| v1.3.0 | Create rooms from the Rooms page |
| v1.3.5 | Manual rooms show a simplified card |
| v1.3.6 | Manifest bump to bust panel JS cache for render-split testing |
| v1.3.7 | Rooms: compact card spacing (padding/gaps/fonts only) |
| v1.4.0 | Release 1.4.0 |
| v1.4.1 | Dead-time optimal-start pre-heat (Tier 0) |
| v1.4.2 | Outdoor HA fallback + low-load duty cycling (Tier 0) |
| v1.4.3 | Load-aware health + condensing return pull-down |
| v1.4.4 | ΔT gas estimate + HA schedule → preset (Tier 1) |
| v1.4.5 | Optional occupancy (phones) + docs wiki + README |
| v1.4.6-dev2 | OTA success detection: no false-fail on stale version |
| v1.4.6-dev3 | Board offline vs OT not linked; LWT + `ot_valid` |
| v1.4.6-dev4 | Node-agnostic backend: follow any live HCS board |

### 4.4 v1.5 – v1.7 — settings, tiers, diagnostics (2026-08-27 – 09-02)

| Version | Change |
|---|---|
| v1.5.0 | Release 1.5.0 |
| v1.5.1 | Stop rediscovering the same HCS board as a new device |
| v1.5.2 | Room setpoints no longer reset to 20 °C after ~5 s |
| v1.5.3 | Panel room-temperature input was never sent |
| v1.5.4 | Optional wind compensation for the heating curve |
| v1.5.6 | Restore the Wind compensation toggle in Configure |
| v1.5.7 | Editable Settings page in the app panel |
| v1.5.8 | Restore Settings tab rendering |
| v1.6.1 | Raw websocket schema mapping for the Settings command |
| v1.6.4 | Switch track had no display — width/height were ignored |
| v1.7.0 | Tier 3 + Tier 4: solar trim, CO2 flag, radiator metering, balancing |
| v1.7.1 | Switch flips no longer kick the user to HA Overview |
| v1.7.3 | Presets are absolute temperatures, not offsets (user revert) |
| v1.7.4 | Balance report suggests a TRV opening-degree cap for oversized rooms |
| v1.7.5 | Setup analyzer: capabilities checklist + suggestions in Diagnostics |
| v1.7.6 | Heating-curve chart in Diagnostics |
| v1.7.7 | Balance auto-cap written to the TRV (opt-in) |
| v1.7.8 | Diagnostics compact layout; restore curve chart function |
| v1.7.9 | Rooms tile fused into setbacks + Tier 3/4 table; access fix |
| v1.7.10 | Diagnostics grid gap 8 → 14 px |
| v1.7.11 | Diagnostics vertical flex stack: no overlaps; honest curve message + retry |
| v1.7.12 | Fuse Diagnostics into one vertical flex stack |
| v1.7.13 | Fuse Min/Max flow into one "Flow limits" card |

### 4.5 v1.8 – v1.14 — Auto-Optimize and correctness (2026-09-20)

| Version | Change |
|---|---|
| v1.8.0 | Auto-Optimize master gate + health guardrails for auto-cap |
| v1.9.0 | Auto-Optimize writers: curve autotune behind the gate (probe mode), auto-flow-cap condensing trim |
| v1.9.1 | Persist balance verdicts + auto-cap cooldown across reloads/updates |
| v1.9.2 | Analyzer skips valve suggestion for manual rooms; footer reads manifest |
| v1.9.3 | Manual rooms are observation-only for every per-room suggestion |
| v1.9.4 | Analyzer room dict attribute name (`heater_control`) fixed |
| v1.10.0 | Anti-railing relax walk for the autotuner; balance flush every 15 samples |
| v1.10.1 | Climate platform setup crash: TRV readout before entity attach wiped all rooms |
| v1.10.2 | Remove setup-time TRV seeding that still crashed the platform |
| v1.11.0 | Climate setup no longer writes HA state before attach; Auto-Optimize toggles hot-apply |
| v1.12.0 | Per-room humidity (external RH sensor or TRV `current_humidity`) |
| v1.12.1 | `humidity_sensor` was a bound method and broke JSON serialisation |
| v1.12.2 | Edit-room save can no longer wipe devices from a stale form |
| v1.12.3 | Server contract test: absent device fields never wipe config |
| v1.13.0 | Statistics page: daily gas/cost/heat-demand/outdoor buckets + 30-day trend |
| v1.13.1 | Unload crash: stats flush referenced an undefined local |
| v1.13.2 | Guarded custom-element define so a stale module cannot keep the old panel alive |
| v1.13.3 | Refuse a smart-room save with zero TRVs |
| v1.14.0 | Room save reloads the entry once (nested unload was emptying every room) |

### 4.6 v1.15.x — floor plan, hardening, valve direct (2026-09-20 – 10-03)

| Version | Change |
|---|---|
| v1.15.0 | Remaining audit: backup on every room write, multi-TRV form, preset temps, visible control-loop errors |
| v1.15.1 | Version 1.15.1 |
| v1.15.2 | Floor plan: uniform responsive bands + humidity in room tiles |
| v1.15.3 | Stats: daily heat-demand + gas bar charts |
| v1.15.4 | Heat demand reported as an average % (1-day + 30-day) |
| v1.15.5 | Self-healing CH commands: reconcile commanded state against boiler telemetry |
| v1.15.6 | Security + robustness: admin-gate room/OT-log control, block SSRF from discovery, flow-setpoint self-heal |
| v1.15.7 | Persisted cooldown clock, OTA verify storm, occupancy hot-toggle, gas reset/flush, rename balance migration |
| v1.15.8 | Comfort/measurement fixes: window invalidation + seeding, outdoor fallback, NaN guards, shallow setbacks |
| v1.15.9 | Frontend fixes: poll reconnect, stale edit-zone freeze, XSS escapes, apply-temp guard |
| v1.15.10 | Robustness: tick overlap guard, sensor availability, unified ranges, dead-code cleanup |
| v1.15.11 | Hardening: corrupt-store guards, duty-cycle hot-apply, sensor-listener teardown, validation |
| v1.15.12 | Status poll no longer mutates zone state; learning-module faults logged |
| v1.15.13 | Dedupe learned-store persistence; memoise the per-tick zone decision |
| v1.15.14 | OTA mirror serves the ECDSA signature alongside the image |
| v1.15.15 | OTA: mirror always refreshes, catalog force-refresh, qos1, auth-broken HTTP fallback dropped |
| v1.15.16 | Stale firmware-update entity + boiler/failsafe sensors without data |
| v1.15.17 | Gas-optimisation logic gaps |
| v1.15.18 | Auto-Optimize + auto-flow-cap ON by default |
| v1.15.19 | Secret Debug screen: live HCC event feed with real TRV actions |
| v1.15.20 | Room editor draft restore is room-scoped |
| v1.15.21 | Tier 5 "Valve direct" room mode: HCC drives the opening degree |
| v1.15.22 | Valve care, no-op setpoints, room health sensors, central mode |
| v1.15.23 | Empty floor plan after v1.15.22: select platform file was misnamed |
| v1.15.24 | Manual temperature overrides presets and aligns to preset temps |
| v1.15.25 | Internal development tier labels removed from user-facing text |

### 4.7 v1.16 – v1.19 — learning, audits, HA compatibility (2026-10-03 – 10-15)

| Version | Change |
|---|---|
| v1.16.0 | Closing-degree-only valves with inverted logic |
| v1.17.0 | Self-learning: setup-time dispatch, train-now, skip-reason visibility, tab hints |
| v1.17.1 | Debug tab: live per-room TRV state table above the feed |
| v1.17.2 | Version 1.17.2 |
| v1.17.3 | Learner: 10-minute training windows + reserved AI ring in the debug feed |
| v1.17.4 | Learner: heating-weighted fits, per-room shadow scorecard, model rollback |
| v1.17.5 | Solar trim: HA sun position as a conservative fallback |
| v1.17.6 | Audit blockers: TRV downward pushes, valve close on OFF/outage, discovery hardening, learner lifecycle |
| v1.17.7 | Audit fixes: manual-temp trap, exercise button/aborts, close bypass, weighted alignment, orphan purge, crash guard |
| v1.17.8 | HA 2026.10 compatibility: sensor platform regression, bootstrap wrap-up, scheduling helpers |
| v1.17.9 | Window detection: sustained heat-escape pause without contact sensors |
| v1.18.0 | Audit fixes (re-point): floor-mode activation, rename migration, flow-curve exclusion, mixer gating, write-failure latches |
| v1.18.1 | Bidirectional TRV setpoint sync: targets changed at the TRV are adopted |
| v1.18.2 | Airflow-blockage watch: TRV satisfied while the room starves (diagnostic only) |
| v1.18.3 | Full re-audit: entity `hass` attribute, slope setpoint wiring, occupancy writes, NaN guards, readback clamp guard, staleness |
| v1.18.4 | Whole-app logic flows + audit fixes: `check_updates` gate, mirror trust gate, `decision-flows` doc |
| v1.18.5 | Version 1.18.5 + wiki stage |
| v1.19.0 | Backlog pass (re-point): duty kW map, autotune kW weighting, design-outdoor option, floor exclusion, escape cap |
| v1.19.1 | Mirror drops a cached pair on catalog-digest mismatch (the stale-pair drain that failed signature checks forever) |

### 4.8 v1.20 – v1.23 — CI and delivery honesty (2026-10-15 – 10-30)

| Version | Change |
|---|---|
| v1.20.0 | Version-agreement check reads the manifest instead of a pinned literal |
| v1.20.1 | pyflakes gate clean package-wide; restore two `CONF_WIND` names; wire the missing `HEAT_CONTROL_FLOOR` import |
| v1.21.0 | Version labelled (const + manifest); retained ctl mirror carries `tset_cap`; anti-stick sweep bound to the room entity |
| v1.22.0 | Keep-alive feed: a stable room is re-written at most every 5 min, preventing TRVZB internal-sensor fallback |
| v1.22.1 | Debug valve column renamed "Valve cap" (TRVZB publishes the reachable position, not the live one) |
| v1.22.2 | Compatibility floor declared honestly: manifest and `hacs.json` set to 2026.10.0 |
| v1.22.3 | GitHub Actions revived (tag triggers, `cryptography` test dep); per-node backend diagnostics; docs truthed |
| v1.23.0 | CI manifest version gate was grepping the literal `$VER`; quoting fixed |

### 4.9 v1.24 – v1.32 — resilience, binding, batteries (2026-10-31 – 11-04)

| Version | Change |
|---|---|
| v1.24.0 | Radiator power entered in W (validated 0–20 000 W, stored internally in kW; legacy `radiator_kw` accepted) |
| v1.24.1 | Fold fix: stage the handler pass-through the previous fold forgot |
| v1.25.0 | Deaf-hub self-heal: re-assert the `hcs/#` subscription every 5 min; persistent notification after 15 min without telemetry |
| v1.25.1 | OTA ten-failures root fix: dual-channel delivery (HTTP-direct with board password, MQTT fallback) + independent version proof |
| v1.25.2 | CI: otlog gate asserts synchronous render output (removes a DOM-timing flake class) |
| v1.25.3 | Ingestion observability: count every delivered `hcs/#` message, keep the last 10 raw topics |
| v1.26.0 | Pull-based OTA: publish `latest.json` on the hub's static route; boards on HCS ≥ 1.5.30 self-apply within 6 h |
| v1.26.1 | Label bump caught by the tag-version gate before shipping |
| v1.27.0 | HTTP-primary telemetry: poll each board's portal every 60 s; MQTT remains the fast secondary feed |
| v1.28.0 | Process-uptime dial in the footer (`process_uptime_min`); restart state is readable |
| v1.29.0 | Boiler card reads the values the hub already has |
| v1.29.1 | A blank telemetry replay no longer erases outdoor, flow or return |
| v1.29.2 | Stale retained board announcements can no longer steal adoption |
| v1.30.0 | Explicit one-app-to-one-board binding |
| v1.30.1 | Device page is one compact linked-board view |
| v1.31.0 | One merged Device card |
| v1.31.1 | Remove redundant Device tab text |
| v1.32.0 | Room battery levels: TRV `🔘` and temperature-sensor `🌡` chips on room cards and floor-plan tiles |

### 4.10 Version gaps in HCC

These numbers were allocated but never tagged. They are not missing releases.

| Range | Missing | Note |
|---|---|---|
| v1.3.0 – v1.3.7 | 1.3.1 – 1.3.4 | Panel render-split iteration; no tags created |
| v1.5.0 – v1.5.8 | 1.5.5 | Skipped |
| v1.6.1 – v1.6.4 | 1.6.2, 1.6.3 | Panel settings iteration |
| v1.7.0 – v1.7.13 | 1.7.2 | Skipped |

The tag count (172) and the semver count (169) differ only by the three
`v1.4.6-dev*` tags.

## 5. HCS release ledger

### 5.1 v0.x — gateway foundation (2026-08-22 – 08-23)

| Version | Change |
|---|---|
| v0.3.0 | Gateway software (M1–M4), C3 mini direct fitment, flasher page |
| v0.4.0 | Gateway role auto-detect (`auto` / `gateway` / `master_only`) |
| v0.5.0 | 1-Wire DS18B20 support + Sensors web tab |
| v0.6.0 | Boiler diagnostics: decoded fault text on web UI, API and MQTT |
| v0.7.0 | Boiler capabilities: pressure, DHW control, identity, fault history, gateway reference mode |
| v0.8.0 | Connection-loss failsafe for unattended freezing weather |
| v0.9.0 | Boiler member-ID topic for manufacturer auto-detection |
| v0.9.1 | MQTT connectivity fixes + link visibility |
| v0.9.2 | Status JSON rebuilt; verified live OTA to both bench devices |

### 5.2 v1.0 – v1.3 — stable firmware (2026-08-23 – 08-25)

| Version | Change |
|---|---|
| v1.0.0 | Firmware 1.0.0; boot fix for the `#else` eaten by an identity edit (network bring-up was compiled out) |
| v1.0.1 | Placeholder-host fix |
| v1.0.2 | Bug fixes |
| v1.1.0 | Auto-detect 1-Wire probes + custom roles |
| v1.1.1 | OTA progress reporting to MQTT |
| v1.2.0 | Settings sync over MQTT (two-way mirror for HA) |
| v1.2.1 | Scheme-aware OTA client (plain-HTTP pulls) |
| v1.2.2 | Subscribe `dhw_setpoint` over MQTT + retained ctl snapshot |
| v1.3.0 | OTGW compatibility layer purged; native `hcs/` topics are the only contract |
| v1.3.1 | Power-health telemetry + C3 radio headroom |
| v1.3.2 | OpenTherm console: on-board OT frame log |
| v1.3.3 | Fix dead device web UI (two page-script syntax errors) |
| v1.3.4 | C3 1-Wire on GPIO1 (D5 pad) + diagnostic status LED on all boards |
| v1.3.5 | Six bugfixes: 1-Wire d1_mini, stale sensors, power health, `wc_target`, failsafe CH, JSON escape |
| v1.3.6 | Final: OT Status READ_DATA fix in both poll paths; verified live on the boiler |

### 5.3 v1.4 — brick and recovery (2026-08-26 – 08-27)

| Version | Change |
|---|---|
| v1.4.0 | `LittleFS.begin()` portable for ESP8266 (no format argument) |
| v1.4.1 | OT console MsgIDs + cleaner Toutside/Tret for 1-Wire inject |
| v1.4.2 | Boiler OT priority for Tout/Tret; 1-Wire only backfills |
| v1.4.3 | OT link hysteresis + thin poll (stop UI flicker and API errors) |
| v1.4.4 | Stop the HTTP self-probe reboot loop + system log console |
| v1.4.5 | Always publish MQTT telemetry + `ot_valid` topic |
| recovery-v1.4.9 | USB recovery guide + standalone recovery project (non-release tag) |
| v1.4.11 | OT console crash fix + self-probe removed |
| v1.4.12 | OT link flap: Status retry + longer hysteresis |

The 1.4.6–1.4.9 window is the C3 bricking sequence, documented in
`docs/wiki/Changelog.md` but never tagged as normal releases: the ISR not
being `IRAM_ATTR` caused a PANIC loop before Wi-Fi; 1.4.7 added the full IRAM
ISR chain plus OT safe-mode after three unclean boots; 1.4.8 removed the
WS2812/RMT status LED after an `abort()` in `rmt_driver_install`; 1.4.9 is the
USB recovery path. Versions 1.4.6, 1.4.7, 1.4.8, 1.4.9 and 1.4.10 have no
release tag.

### 5.4 v1.5.0 – v1.5.20 — security and signed OTA (2026-08-27 – 09-24)

| Version | Change |
|---|---|
| v1.5.0 | Audited stable |
| v1.5.1 | Wi-Fi event logging (diagnose silent drops) |
| v1.5.2 | Gateway slave ISR all-IRAM (parity with the master path) |
| v1.5.4 | Bulletproof Wi-Fi: active re-association, TX power, driver properties |
| v1.5.5 | Status LED toggle + brightness on Settings (MQTT + web), persisted |
| v1.5.6-test | Wi-Fi wedge self-heal restart, OTA/reboot race guard, `/api/wifi` diagnostics, runtime TX power (test tag) |
| v1.5.6-test2 | Wire `bulletproofWifiTick` into `net.loop` (it was orphaned), heal tests, safe TX knob (test tag) |
| v1.5.7-test | Loop watchdog (ESP32, 20 s), OTA WDT pause, persisted reboot reason (test tag) |
| v1.5.8 | C3 Mini TX 8.5 dBm after begin, no disconnect/begin thrash, HT20 + `PS_NONE` after associate |
| v1.5.9 | Plain-LED blink family + active-low restore (D1/S2), portal secrets never echoed, open setup/recovery AP |
| v1.5.10 | 1-Wire pins owned by board envs; `/api/status` and OTA auth use live settings |
| v1.5.11 | Gateway link self-heal, retained-command dedupe, OT parity validation, portal field fix |
| v1.5.12 | Security: exact-origin CSRF guard, OTA URL validation, `/api/ota` origin check |
| v1.5.13 | Secure by default: MAC-derived admin password + recovery AP/update auth |
| v1.5.14 | Web auth flow: create password → login, with enable/disable toggle |
| v1.5.15 | In-page login form with session cookie + logout |
| v1.5.16 | MQTT/OT nits: escape `device_name` in discovery, subscribe `set`/`led`, sanitise node id |
| v1.5.17 | Signed OTA: ECDSA P-256 image verification + streamed download |
| v1.5.18 | OTA rollback watchdog: OT link counts as healthy + health latch |
| v1.5.19 | Auth toggle fix: disabling authentication no longer requires a login |
| v1.5.20 | Publish `boiler_diag`/`failsafe` every tick (drop stale change-gating) |

### 5.5 v1.5.22 – v1.5.26 — toolchain and ceiling (2026-10-15 – 10-16)

| Version | Change |
|---|---|
| v1.5.22 | Deinit+init WDT (reconfigure exists only in newer IDF minors) |
| v1.5.23 | Fixed-toolchain OTA batch: exact pioarduino + arduino-esp32 commit pinning, ESP8266 joins the signed OTA chain, OT slave ring buffer, DHW setpoint clamped at the command boundary |
| v1.5.24 | Honest OTA size budget: drop exceptions/RTTI (~80 KB per image), per-env CI budget, `Update.begin` failure reports size and cause |
| v1.5.25 | Learned boiler CH ceiling: three write-ACK echoes latch a real ceiling; wire writes clamped with a ~5-min probe; `tset_cap` published |
| v1.5.26 | The learned ceiling ships in the retained `ctl` mirror too |

v1.5.21 has no tag: the toolchain drift broke CI and the release never shipped.
v1.5.23 exists specifically to make that class impossible.

### 5.6 v1.5.27 – v1.5.32 — MQTT death and pull updates (2026-11-02)

| Version | Change |
|---|---|
| v1.5.27 | Zombie-MQTT-session guard: keepalive 30 s, rebind when no inbound frame lands for 90 s |
| v1.5.28 | Session rebinding made honest: unconditional 6 h max-age rebind instead of the inbound-decay trigger |
| v1.5.29 | Portal exposes `mqtt_connected` (session view) and `mqtt_outbound_ok` (last accepted batch within 5 min) |
| v1.5.30 | Pull-based self-update: fetch the hub's `latest.json` over plain LAN HTTP, self-apply a newer signed release |
| v1.5.31 | ESP8266 collects Origin and Cookie through the variadic header API (the array form is ESP32-only) |
| v1.5.32 | A missed outdoor or return read keeps the last temperature instead of publishing nothing |

### 5.7 HCS version gaps

| Range | Missing | Note |
|---|---|---|
| v1.4.0 – v1.4.12 | 1.4.6 – 1.4.10 | Brick/recovery window; documented in the changelog, not tagged |
| v1.5.0 – v1.5.32 | 1.5.3 | Skipped |
| v1.5.0 – v1.5.32 | 1.5.21 | Toolchain drift broke CI; never shipped |

## 6. Branding ledger

### 6.1 The decision

On 2026-08-23 the project held a branding review before the public 1.0 line.

| Step | Commit | What happened |
|---|---|---|
| Candidate set | `3cfc242` | Five thumbnail directions committed under `docs/branding/candidates/`: **A** ember hero, **B** minimal light, **C** zone cards, **D** heating curve, **E** HA cards |
| Direction chosen | `bc8fefc` | **A — ember hero** approved by the owner; the decision is recorded in `docs/branding/LOGO-BRIEF.md`. The other four candidates were deleted in the same 1.0 branding pass |
| Assets produced | `9c01e59` | Banner (`banner.svg` promoted out of candidates), `banner-1280.png`, social preview, `logo.svg`, `logo-1024.png`; sidebar panel logo in v1.1.0 |
| README | `0bd9c4c` | PNG banner used instead of SVG — SVG is unreliable through GitHub's camo proxy |

Why A: the project's tone is *warmth against cold, engineering-grade calm*. The
approved reference is a dark navy night scene with one warm flame. The house
outline carries "home", the flame carries "heat", and the mark has to survive
the two places it actually appears: the HA sidebar at 24–32 px and the HACS
store card.

### 6.2 Fixed brief (from `docs/branding/LOGO-BRIEF.md`)

| Constraint | Rule |
|---|---|
| Motif | Flame within a house outline (primary); flame in a rounded-square badge; house with an ember-lit opening |
| Palette | Night navy `#0B1220` → `#1A2230`; flame orange `#F59E0B`; inner highlight `#FFC454`; optional cool `#38BDF8`; text `#FFFFFF` / `#9FB3C8` |
| Typography | Geometric sans (Inter / Manrope / Montserrat SemiBold); wordmark exactly "Home Climate Control"; banner tagline only |
| Legibility | Must read at 24–32 px; no stroke thinner than ~6 % of canvas width; no fine detail inside the flame |
| Do-nots | No photorealism, no clip-art, no more than two accent colours, no text inside the square mark, no 3D, no heavy shadows |
| Tone | warm · reliable · efficient · engineering-grade calm · open-source |

### 6.3 Asset delivery timeline

| Date | Commit / release | Delivery change |
|---|---|---|
| 2026-08-23 | `7041574` | Root `logo.png` / `icon.png` for HACS variants that read repo-root images |
| 2026-08-23 | `551578d` | Local `brand/` folder ships `icon`/`logo` at 1× and 2× (HA 2026.3+ mechanism) |
| 2026-08-23 | `5527182` | `docs/branding/brands/` PNG set (256/512/1024) prepared for a `home-assistant/brands` submission |
| 2026-08-23 | `26cf7a3`, `2f47ba9` | High-contrast social-preview variant; square export for the GitHub social preview / HACS card |
| 2026-08-23 | `2204db7` | Resized to HA spec (256/512 shortest side) — oversized exports could hit proxy limits |
| 2026-08-23 | `0b7fbf3` | Update entity shows the bundled logo on any HA version via `www/brand/` |
| 2026-08-23 | **v1.0.10** | `brand/logo` normalised to 1× ≤ 256, 2× = 512 |
| 2026-08-23 | **v1.0.14** | Origin-relative cache-busted icon URL — absolute `get_url` links break off-origin |
| 2026-08-24 | **v1.1.0** | Panel logo in the sidebar app |
| 2026-08-28 | `22f2821` | Documented that HA 2026.3+ proxies `brand/` locally first; the `home-assistant/brands` submission was dropped in favour of the inline folder (custom-integration PRs there are auto-closed) |

### 6.4 Current asset state (verified 2026-11-06)

| Asset | Size | Purpose |
|---|---|---|
| `custom_components/home_climate_control/brand/icon.png` | 256 × 256 | HA integration icon (1×) |
| `custom_components/home_climate_control/brand/icon@2x.png` | 512 × 512 | HA integration icon (2×) |
| `custom_components/home_climate_control/brand/logo.png` | 256 × 256 | HA integration logo (1×) |
| `custom_components/home_climate_control/brand/logo@2x.png` | 512 × 512 | HA integration logo (2×) |
| `custom_components/home_climate_control/www/brand/icon*.png` | 256 / 512 | Update-entity icon served from the static path |
| `docs/branding/banner-1280.png`, `logo.svg`, `logo-1024.png`, `social-*.png` | — | Repository presentation |
| `docs/branding/brands/*.png` | 256 / 512 / 512 / 1024 | Prepared brands-repo set (not submitted) |
| Root `icon.png`, `logo.png` | 1024 × 1024 | Legacy HACS root images — see drift §8 |

## 7. Decisions and invariants

These were made once and are still binding. They are recorded here so a future
session does not re-litigate them.

### Release discipline

1. A release ships only after the user's explicit go; field testing is the
   user's gate afterwards.
2. Release notes are impersonal. Competitor app names never appear in notes.
3. UI copy describes behaviour only — never "better than <app>", never filler.
4. **Never bump the version to correct a mistake.** A correction amends the
   same release: amend the commit, force-update the tag, rewrite the notes in
   place. Bump only for genuinely new scope.
5. The packaged version label must match the tag; CI enforces it on tag builds
   in both repos.
6. Release candidates are deleted once the stable release ships.
7. Doc-only changes (like this ledger) are committed without a version bump and
   without a tag.

### Hardware and control rules

8. Boot must start with CH off. No exceptions.
9. TRV `temperature_accuracy` bands are not changed.
10. The MAC-derived default portal password stays. MQTT command authentication
    is intentionally skipped.
11. Health flags (struggling, airflow blockage) are diagnostics only; they
    never drive control.
12. Unknown gas gaps stay under-counted — an honest bill beats an invented rate.
    The board clamps OpenTherm writes to the boiler's real limits.
13. One app installation binds to exactly one board. No automatic adoption,
    and a stale retained announcement cannot steal the binding.
14. Chips: `🔘` = TRV battery, `🌡` = temperature-sensor battery. `🎛️` is
    banned (reads as a window), `🔥` is not a TRV. Emoji only — no SVG glyphs.
15. Battery source: entity attribute first, else a `device_class: battery`
    sensor on the same HA device via the registry; weakest wins; `≤ 20 %` is
    low. Rooms without data show nothing at all.
16. The learner shadows; it never controls until explicitly promoted.
17. The ESP32 merge of HCC into HCS stays parked (§9).

## 8. Documentation drift (as of 2026-11-06)

Both repositories carry documents that no longer match what ships. None of
these affect behaviour; all of them mislead a reader.

| File | Says | Truth |
|---|---|---|
| `README.md` line 21 | Current version **v1.7.13** | v1.32.0 |
| `README.md` line 87 | Home Assistant **2024.1+** | manifest and `hacs.json` require 2026.10.0 |
| `README.md` line 134 | "Tier — Status (v1.4.5)" | Tiers 0–5 shipped long ago; internal tier labels were removed from UI in v1.15.25 |
| `README.md` line 146 | Companion firmware **HCS v1.4.0** | v1.5.32 |
| `README.md` vs `readme.md` | Two different README files are tracked | GitHub and HACS display `README.md`; the newer branding README (`readme.md`, 2026-08-23) is effectively hidden |
| `readme.md` line 11 | Badge "HA 2024.1+" | 2026.10.0 |
| `readme.md` line 30 | "Highlights (v1.0.0)" | 32 minors behind |
| `readme.md` line 79 | Floor plan "Placeholder (coming later)" | Floor plan shipped in v1.15.2 (2026-09-20) |
| `docs/wiki/Home.md` line 8 | Current version **v1.5.7** | v1.32.0 |
| `docs/hacs-default-pr.md` | "continuous releases since 2024", "current version v1.5.3", "283 unit tests" | First commit is 2026-08-22; current version 1.32.0; 579 test functions across 74 test modules |
| HCS `README.md` lines 21/32/62 | Current firmware **v1.5.0** | v1.5.32 |
| HCS `docs/wiki/Changelog.md` | Latest entry **v1.4.8** | v1.5.32; the 1.5.x line has no changelog entries |
| Root `icon.png` / `logo.png` | 1024 × 1024, 76 KB | Not normalised to the HA spec used by `brand/`; legacy copies from 2026-08-23 |

The docs-drift list is maintenance work, not a release. Fixing it must not bump
the version or move a tag.

## 9. Parked and open

### Parked by explicit decision

- **Merge HCC into HCS on an ESP32** — the analysis is preserved in
  `docs/HCC-HCS-COMPACT-2026-10.md`. RAM, CPU and flash are not the blockers
  (app 1.3 MB in a 1.44 MB slot, 68 KB static DRAM, ~15 KB state per room).
  The costs are porting the Python control plane to C++ (2–4 disciplined weeks
  with test parity), keeping Zigbee/TRV control external, and sourcing HA-side
  inputs. If it ever opens, start with a thermostat-first core (zones + PID +
  schedule + curve + failsafe) behind a build flag on a 16 MB board.
- **TRVZB control-band management** — declined by the user; factory −1.0 bands
  stay (living room is the −0.2 reference).
- **`home-assistant/brands` submission** — dropped in favour of the inline
  `brand/` folder.

### Waiting on data or hardware

- Post-cap balancing verification pass.
- AI promotion criteria (the learner is still shadow-only).
- Floor pre-heat — needs a pilot underfloor-heating room; user decision.
- ESP8266 signed OTA — field verification when such a board is deployed.

### Unscheduled ideas

- WebSocket push instead of panel polling.
- Automatic room-area / radiator-power inference (manual config shipped; the
  inference is an idea only).

### Verification pending from the user

- Field test of the v1.32.0 battery chips (`🔘` / `🌡`) on room cards and
  floor-plan tiles. Code, data path and live payload are verified; the visual
  rendering is the user's call.

## 10. Maintaining this ledger

- Add a row when a tag ships, in the same commit as the version bump.
- Record the release note subject, not an interpretation of it.
- When a decision changes, edit the decision and note the date; do not delete
  the old entry silently.
- Keep the drift table honest — strike a row when the doc is fixed.
- This file is documentation. It never carries a version bump.
