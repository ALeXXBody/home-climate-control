# Audit — v1.4.0 (2026-08-26)

Full audit of **Home Climate Control** (HCC) and companion **Home Climate System** (HCS) firmware. UI/visual layout left unchanged (room cards stay as beta1.2).

## Verification
- HCC: **235** tests passed
- No panel CSS/HTML layout changes in this release

---

## HCC fixes shipped

| Sev | Issue | Fix |
|-----|--------|-----|
| Crit | `device_control` / room mutators open to non-admin WS users | `@require_admin` on device_control, add/remove/rename zone, calibrate, set_boiler_info |
| Crit | `set_zone` could drive any `climate.*` | Restrict to HCC zone entity_ids |
| Crit | BoilerInfo MQTT sub lost after entry reload | Resubscribe if `_unsub is None`; pop `_ACTIVE` on unload |
| Crit | OT log proxy `NameError: aiohttp` | Use `asyncio.timeout` (no bare aiohttp) |
| Crit | WC curve MQTT JSON vs firmware CSV | Publish CSV `"ref,design,fmax,fmin"` |
| High | Multi-window sensors: last event wins | Aggregate `any(sensor open)` |
| High | Manual heat_control still commanded TRVs / demand | Skip demand, PID, TRV push when manual |
| High | Update-entity OTA missing `target_version` | Pass catalog version into `async_trigger_ota` |
| High | Calibration cancel needed zone; HVAC not restored | Cancel without zone; restore prev HVAC mode |
| High | Rename rejected device-only edits | `device_fields` counts as a change; validate entity domains |
| Med | Heartbeat from set/ traffic | Remove second unconditional `_last_rx_mono` |
| Med | Retained CH/flow commands | Default `retain=False` on boiler commands |
| Med | PID integral held when idle | `pid.reset()` when not demanding |
| Med | setback `heating_allowed` ignored | Early return when False |
| Med | Datalogger stop lost buffer | `await _async_write` on stop |
| Med | Firmware manager leaked on last unload | `async_stop` + clear from hass.data |
| Med | Mirror path traversal | Basename + `firmware-[A-Za-z0-9_]+\.bin` only |
| Med | Catalog notes operator-precedence | Parentheses around published fallback |
| Med | Failsafe range | flow 10–90, grace 1–120 |
| Med | min_flow ≥ max_flow in options | Reject with `min_flow_above_max` |

## HCS firmware fixes (companion repo)

| Sev | Issue | Fix |
|-----|--------|-----|
| Crit | ESP32 WC settings never saved to NVS | Persist wc_en/ref/dsn/fmax/fmin |
| Crit | OTA rollback dead (no LittleFS mount / pending not loaded) | `LittleFS.begin` + load pending every tick |
| High | HTTP DHW setpoint ignored | Handle `dhw_setpoint` in `/api/control` |
| High | OT getters treat 0 as valid temp | Only update snapshot on SUCCESS + t>0 |
| High | 1-Wire return inject overwritten | Re-apply inject after OT return read |
| High | `/api/reboot` unauthenticated | Require `authOk()` |
| Med | referencePoll omitted DHW enable bit | Include 0x0200 when DHW enabled |

## Deferred (documented, not blocking 1.4.0)
- Full discovery-URL SSRF allowlist (partial hardening via mirror basename)
- Runtime MQTT prefix application in firmware
- platformio.ini orphan build_flags ownership
- Per-entry Store keys for multi-install
- Gateway thermostat timing / role persistence
- Command watchdog when MQTT up but HA hung

## Residual risk
LAN-trusted device APIs without OTA password remain open by design for setup.
