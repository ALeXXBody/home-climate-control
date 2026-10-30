# HCC & HCS — project compact (Oct 2026)
This document replaces sessions "HCC&HCS: 1/2/3" (Aug 24 – Sep 27, 2026).
It is the single source of truth for current state, closed threads and
the remaining plan. Update it instead of resurrecting old sessions.

## The system, in one paragraph
Home Climate Control (HCC) = a HA custom integration + localStorage-backed panel
that orchestrates rooms via addressable TRVs (Sonoff TRVZB on Zigbee2MQTT),
a connection-loss failsafe, weather-comp/duty/condensing logic, autotune and
AI-shadow learning (never controlling until promoted). Home Climate System
(HCS) = the OpenTherm board firmware (ESP32 D1 mini deployed at 192.168.50.21;
partitions_xl_ota; ECDSA-signed OTA; learned boiler ceiling). HCC drives the
board over retained MQTT; Z2M carries the TRVs; the user's automations feed
external temperatures (now also HCC-keeper-fed).

## Current state (2026-10-30)
- HCC **v1.23.0** · HCS **v1.5.26** — both tagged on green CI.
- Repos: ALeXXBody/home-climate-control · ALeXXBody/home-climate-system (public).
- CI: both repos run on every push + tags (public = free Actions minutes).
  HCC verifies the packaged label against the pushed tag on tag builds
  (added after the 1.21/1.23 mislabel incidents — never ship a version the
  footer disagrees with).
- Live house: all TRVZB temperature sources = remote_temperature (keeper
  re-asserts + feeds external inputs, keep-alive ≤5 min); stuck-valve failover
  ready; no drift/failover flags live; boiler ceiling learned at 55 °C on the
  board (hub-side display pending user's Redownload to 1.23.0 →
  `backend_nodes` appears → trace closes).
- Learner retrains weekly (last 2026-10-25); datalogger in
  /config/home_climate_training/data-YYYY-MM.jsonl.

## Closed threads from the first three sessions (where they resolved)
- Floor plan UI, OpenTherm console UI, wifi self-probe fixes, ElegantOTA
  removal → shipped (board firmware + panel gates).
- All-8-boards signed releases on every tag → HCS CI (stale-asset class hard).
- Boiler web-layer wedges / C3 modem-sleep → removed by the 2026 rework
  (the fleet migrated to the ESP32 D1 mini; the .137/.153/.195 saga retired).
- Datalogger cold-start compromise → replaced by the data contract
  (./docs/functions-analysis.md E18) and the datalogger module.
- Zone-rename races, reload loops, dedupe guards → test_lockers in
  tests/ (575+ tests, panel DOM gates, pyflakes — all green).
- Insulation scoring → shipped; v1.23.0 additionally scales learned setback
  depth by k (poor ×0.8 … excellent ×1.15, 1–5 °C clamps, maturity-gated).
- TRVZB temperature-source flaps (#29650, unfixed upstream) → the keeper:
  HCC feeds external temps, re-asserts drifted selects, drift watch.
- Marketplaces readiness (2026.11) → declared floors (hacs.json/manifest
  2026.10.0), repositories migrate automatically, nothing further needed.
- Room areas/radiator-power: manual config + duty maps shipped (v1.19.0);
  (auto-"inference" from data remains an idea only).

## Parked idea — "side quest": merge HCC into HCS on an ESP32
(User-defined: explore in a future conversation.) The analysis done here,
to be picked up as-is:
- RAM/CPU/flash are NOT the blockers (measured: app 1.3 MB in the 1.44 MB
  slot; static DRAM 68 KB; room state KB-scale; learner already streams —
  fit state ≈15 KB/room; littlefs could hold rolling windows ~470 KB).
- The real costs: porting the Python control plane to C++ (2–4 disciplined
  weeks with test parity), the Zigbee side stays external (TRVs need Z2M
  somewhere), and HA-sourced inputs (occupancy, presence, alerts).
- Suggested starting point when this opens: a thermostat-first core
  (zones + PID + schedule + curve + failsafe) behind a build flag on a
  16 MB board, HCC/HA as the dashboard, then grow features in C++ through
  the existing release discipline.

## Standing policies (keep honoring)
1. A release ships only after the user's explicit go; field testing stays the
   user's gate afterwards.
2. RCs deleted once stable ships; release notes impersonal; competitor names
   never appear in notes.
3. Version label must ALWAYS match the tag (CI-gated in both repos).
4. HCS platformpins in platformio.ini: update only with a full local build +
   green CI (toolchain drift broke CI in 1.5.21 before this).
5. Health flags (struggling/airflow-blockage) are diagnostics-only.
6. Gas-gap truths: unknown gaps stay under-counted (honest billing better
   than inventing a rate); the board clamps OT to the boiler's real limits.
7. User handles HA-side changes (HACS/Mkplc, automations); HCC ops allowed
   on boards/portal once the user asks.

Genuinely open threads & immediate next steps
- Waiting on the user's Redownload of **HCC 1.23.0** — after restart,
  get_status → boiler.backend_nodes shows the per-node view → finish the
  tset_cap hub-ingestion trace (board clamps already work).
- Data-gated: post-cap balancing verification pass; AI promotion criteria;
  floor preheat (needs a pilot UFH room — user decision).
- Architecture ideas (unscheduled): WebSocket push instead of panel polling;
  optional TRVZB control-band management (user declined for now).
- ESP8266 signed OTA stays field-verify-when-deployed.
- TRV control bands stay at the factory -1.0 (user declined; living room
  already at -0.2 as the reference).

Key commands
- HCC tests: cd ~/home-climate-control && .venv/bin/python -m pytest tests/ -q
  + node tests/panel_dom_test.mjs (+ pyflakes custom_components/home_climate_control/)
- HCS: pio test -e native · pio run -e <env> (envs list in platformio.ini)
- Fresh live snapshot for any claim:
  ws://192.168.50.20:8123/api/websocket (read-only HA token) →
  home_climate_control/get_status ✓ board /api/status ✓ device UI
- HCS board admin password: test1234 (portal 192.168.50.21; the portal
  password field is separate from MQTT creds).

Lessons etched (do not relearn)
- Never trust a publish without a fresh live snapshot ("here is the current
  live state" > "I believe so").
- OTA delivery: the hub must PROVE (catalog sha + the board's own ECDSA check
  on the exact bytes) before serving; no cache-staleness heuristics.
- Every TRV/integration quirk we documented has a keeper/failover configured
  default-on, so the house reacts instead of waiting for a human.
- Version labels get CI-verified; tags get re-pointed only with green runs.
