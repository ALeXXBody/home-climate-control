# Security & stability audit — 2026-08-23

Full audit of Home Climate Control (HA integration) and the
home-climate-system ESP firmware before/around the v1.0.0 milestone.
Findings marked FIXED shipped on `main`; no release was cut for them.

## Scope

- HCC: custom component (`custom_components/home_climate_control`), panel JS,
  websocket API, MQTT subscriptions, storage
- Firmware: HTTP server surface, MQTT bridge, OpenTherm master/gateway logic,
  settings persistence (NVS/EEPROM)

## Findings

### HCC

| ID | Severity | Finding | Disposition |
|---|---|---|---|
| F1 | Medium | `async_unload_entry` never unloaded the `sensor` platform, never stopped the boiler-info MQTT subscription, and left the update-checker interval running after entry removal | **FIXED** — platforms list now `["climate","sensor"]`; `boiler_info.async_unload()` called; checker stopped when last entry unloads |
| F2 | Low | With multiple config entries, `ws_set_failsafe` pushes to whichever entry iterates first | Documented — single-system usage is the supported model; multi-entry routing tracked for a future release |
| F3 | Info | Secrets (MQTT password) are stored by HA's own config-entry storage; no secret values are logged anywhere | Verified clean |
| F4 | Info | `boiler_info.image_url_for()` builds file paths from user input; slug replaces `/` and spaces so no traversal outside `www/boilers/` | Verified safe |

### Firmware

| ID | Severity | Finding | Disposition |
|---|---|---|---|
| F5 | **High** | Every mutating HTTP endpoint (`/api/control`, `/api/settings`, `/api/failsafe`, `/api/gw/*`, `/api/sensors/*`) was unauthenticated — anyone on the LAN could change heating behaviour or reboot the device. Only `/api/ota` had a password gate | **FIXED** — all mutating endpoints now require HTTP Basic auth (`admin` / OTA password) when a password is configured; read-only `/api/status` stays open |
| F6 | High | Fault-history fetch ran every slow-read rotation (~7 s): each pass issued `2×size` bus transactions | **FIXED** — fetched once at boot, refreshed hourly |
| F7 | Medium | PubSubClient default 15 s socket timeout blocked the entire main loop during every reconnect to an unreachable broker (web UI froze); reconnect interval was fixed 5 s forever | **FIXED** — socket timeout 4 s + exponential backoff capped at 60 s |
| F8 | Medium | DHW remote-parameter write (ID 56) was re-sent every 1 Hz poll cycle while active | **FIXED** — reaffirmed once per minute (thermostat-like cadence) |
| F9 | Low | Capability round-robin reads doubled OpenTherm bus load (1 extra transaction every second) | **FIXED** — throttled to every 3rd poll (~3 s) |
| F10 | Info | Broker host with stray whitespace caused silent no-SYN MQTT failure | Fixed in v0.9.1/v0.9.2 (host sanitised at ingest, state logged, `mqtt_link` exposed) |
| F11 | Info | Long `String +=` status build truncated response head once payload grew | Fixed in v0.9.2 (single JsonDocument + one serialize) |
| F12 | Info | No `sprintf`/`strcpy`/unbounded copies found; EEPROM blob writes use bounded `strncpy` into zero-initialised struct; JSON parsing via ArduinoJson throughout | Verified clean |

## Residual risks (accepted / documented)

- Device web UI and HTTP APIs are intended for a trusted LAN. With an OTA
  password set, mutating endpoints are protected; without one, they remain
  open by design for friction-free setup.
- MQTT credentials rest in device NVS/EEPROM in plaintext (standard for
  embedded devices).
- `/api/status` is read-only and unauthenticated.

## Verification

- Native test suite: 55/55 passing (firmware)
- HA integration tests: 33/33 passing (HCC)
- All 8 firmware environments compile clean
