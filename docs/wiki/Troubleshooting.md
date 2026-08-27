# Troubleshooting

## Integration doesn't appear after install

1. **Restart HA** after copying files or HACS download
2. Check HA logs: **Settings → System → Logs → integration** — look for `home_climate_control` errors
3. Verify files are in the right place: `config/custom_components/home_climate_control/`
4. Check `manifest.json` exists and has valid JSON
5. Make sure HA version is 2024.1+

## Board not connecting (red "Board offline")

> Since HCC 1.5.0 the pill distinguishes **Board offline** (no MQTT telemetry
> from any HCS board — red) from **OT not linked** (board reachable, but the
> OpenTherm bus is down — amber). HCC also follows **any live board**
> automatically; the node id in config is only a preference.

### Check MQTT
1. Install an MQTT explorer (e.g. [MQTT Explorer](http://mqtt-explorer.com/))
2. Connect to your broker
3. Look for `hcs/discovery/#` — you should see discovery JSON from the board
4. Look for `hcs/<node>/online` — should be `online`

### Check node ID
1. The board's node ID is printed on serial at boot: `node_id: hcs-aabbccddeeff`
2. It must match exactly what you entered in the HCC setup wizard
3. Serial monitor: `pio device monitor -b 115200`

### Check MQTT settings
1. Board's MQTT host/port/user/pass must match your broker
2. Open the board's web UI (navigate to its IP in browser)
3. Go to Settings tab → verify MQTT configuration
4. Save → reboot

### Check HA MQTT integration
1. **Settings → Devices & services → MQTT** must be configured
2. HCC discovers boards via MQTT — if MQTT integration is missing, nothing works

## Board pings but web UI times out

1. **Power-cycle the board** (unplug, wait 5s, plug back in)
2. Firmware ≥ 1.4.0 includes auto-reboot on HTTP self-probe failure
3. Try serial monitor to see boot logs
4. If stuck repeatedly, re-flash via OTA from another device

## Rooms not heating

1. Room mode must be **Heat** or a preset — not Off
2. Room temp must be **below** the target temperature
3. Check the **Home** tab — is demand showing for the room?
4. Check the **Diagnostics** tab — is the heating curve producing a flow target?
5. Check the board — is CH enabled? (Devices tab → CH on/off)

## Rooms heating when they shouldn't

1. Check for **manual override** — a preset or mode may be stuck on
2. Check **occupancy** — if home, schedule may be driving the preset
3. Check **schedule** — an active ON window may be applying comfort preset
4. Check the board web UI — CH may be manually enabled there

## Gas estimate is way off

1. **Nameplate kW** must be the **input** rating (not output)
2. **Calibration** multiplier adjusts overall — check against actual meter
3. **Modulation mode** — verify OT modulation is reporting correctly
4. **ΔT mode** — needs both flow and return temps; check return sensor
5. **nomod_factor** — adjust if boiler flame is on but mod reads 0

## Pre-heat not working

1. Need **dead time** and **warm rate** data — calibrate the room or let it learn from several cycles
2. Need an active **schedule** or **occupancy** — pre-heat needs a target time
3. Check **Diagnostics → Pre-heat** — is lead being calculated?
4. Lead must exceed the minimum threshold to trigger

## Duty cycle not activating

1. Need **outdoor temperature** for load calculation
2. Boiler min modulation must be set (default 20%)
3. Demand must be below the min modulation threshold
4. Check **Diagnostics → Duty cycle** — is it enabled and active?

## Presets not changing with schedule

1. Schedule entity must be set in Configure
2. For `schedule.*`: check the schedule is active (not paused)
3. For `input_select`/`sensor`: state must match a known preset name
4. Check **Diagnostics → Schedule** — what entity is configured and what state is it in?

## Board settings not syncing

1. Board firmware must be ≥ 1.2.0 for two-way settings sync
2. MQTT must be connected (check Devices tab)
3. Settings sync uses the `ctl` retained topic — check MQTT explorer

## OTA update fails

1. Board must be on the same network as HA
2. Firmware file must be accessible (HCC mirrors GitHub releases on LAN)
3. Check board's serial monitor for OTA error details
4. If OTA keeps failing, re-flash via USB with PlatformIO

## Panel looks broken after update

**Hard-refresh** the browser: Ctrl+Shift+R (Cmd+Shift+R on Mac). The panel JS is cached.

## Where to find logs

- **HA logs:** Settings → System → Logs → filter by `home_climate_control`
- **Board logs:** Serial monitor (`pio device monitor`) or board web UI → System tab → OT console
- **MQTT logs:** MQTT explorer → watch `hcs/#` topics
