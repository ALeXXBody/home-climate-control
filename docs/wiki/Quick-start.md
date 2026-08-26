# Quick start

After installing HCC ([Install](Install.md)), here's what to do in the first 10 minutes.

## 1. Open the sidebar

Click **Home Climate** in the Home Assistant sidebar. You'll see:

- **Home** tab: outdoor temp, flow temp, boiler status, gas estimate
- **Rooms** tab: your zone cards with thermostats
- **Devices** tab: board control and firmware
- **Diagnostics** tab: detailed internals

## 2. Check the boiler connection

Look at the **header** of the panel:

- **Green "Boiler connected"** = HCS board is online and talking MQTT
- **Red "Boiler disconnected"** = board not found — check MQTT, node id, power
- **Amber** = board found but connection issue (shows diagnostic text)

If disconnected, verify:
- HCS board is powered and on the same network
- MQTT broker is running and accessible from HA
- Board's node ID matches what you entered in setup

## 3. Set a zone to Heat

On the **Rooms** tab, click a zone card and set **Mode** to **Heat**. Adjust the target temperature. You should see:

- The zone card shows the current room temp and your set point
- The **Home** tab shows demand turning on
- The **flow temp** starts tracking the heating curve target
- If the boiler is connected, modulation and flame state change

## 4. Understand the room card

Each room card (single-row layout):

| Left | Center | Right |
|---|---|---|
| Room name + current temp + trend | Thermostat dial | Mode/Profile selector + Edit button |

**Mode/Profile selector** options:
- **Off** — zone disabled, no heating
- **Heat** — active, following set temperature
- **Preset** — eco / comfort / night / away (learned presets with smart setbacks)
- **Auto** — follows HA schedule if configured

## 5. Check diagnostics

Go to the **Diagnostics** tab to see:

- **Curve** — current outdoor→flow mapping
- **Setbacks** — learned per-room night/away depths
- **Dead-time & pre-heat** — estimated warm-up time and lead calculation
- **Duty cycle** — on/off timing when load is low
- **Gas estimate** — current mode (modulation / ΔT / hydronic kW)
- **Schedule** — current schedule source and preset
- **Occupancy** — current presence state and assigned preset (if enabled)

## 6. Calibrate a room

On the **Rooms** tab, click the **Calibrate** button (thermometer icon) on a zone card:

1. Make sure the room is cold (no heating for a while)
2. Click **Calibrate** — the system heats at full for a measured period
3. It calculates the room's **warm rate** (°C/hour) and **dead time** (minutes to start rising)
4. These values power optimal-start pre-heat and setback learning

You don't need to calibrate every room — the system learns from normal operation too. But calibration gives it a head start.

## 7. Enable outdoor fallback (if needed)

If your HCS board doesn't have an outdoor sensor, go to **Configure → Outdoor temperature fallback** and select an HA outdoor sensor or weather entity. This ensures the heating curve works even without boiler outdoor data.

## Next steps

- [Options & settings](Options-and-settings.md) — fine-tune every option
- [Schedule → presets](Schedule.md) — connect HA schedules
- [Occupancy](Occupancy.md) — add phone presence
- [Efficiency tiers](Efficiency-tiers.md) — understand what each feature gives you
