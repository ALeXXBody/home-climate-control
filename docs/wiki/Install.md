# Install

## HACS (recommended)

1. Open **HACS → Integrations** (side menu)
2. Click the **⋮** (three dots) in the top-right → **Custom repositories**
3. Enter:
   - Repository: `https://github.com/ALeXXBody/home-climate-control`
   - Category: **Integration**
4. Click **Add**
5. Find **Home Climate Control** in the list → **Download**
6. **Restart Home Assistant** (Settings → System → Restart)
7. After restart, go to **Settings → Devices & services → + Add integration**
8. Search for **Home Climate Control** and complete the setup wizard

## Manual install (without HACS)

1. Clone or download [the repo](https://github.com/ALeXXBody/home-climate-control)
2. Copy the folder `custom_components/home_climate_control` into your HA config directory:
   ```
   config/custom_components/home_climate_control/
   ```
3. Restart Home Assistant
4. Continue from step 7 above (Add integration)

## Setup wizard

The wizard has two steps:

### Step 1 — Boiler connection

| Field | What to enter |
|---|---|
| MQTT topic prefix | Default `hcs` (matches HCS board default) |
| Board node id | e.g. `hcs-aabbccddeeff` — printed on serial at boot, or found in MQTT discovery |
| Min flow temperature | Lowest allowed flow setpoint °C (default 25) |
| Max flow temperature | Highest allowed flow setpoint °C (default 75) |
| Heating curve coefficient | Starting curve slope (default 1.2); auto-tune adjusts over time |

If you don't have an HCS board yet, choose **Demo mode** instead.

### Step 2 — Zones (at least one)

For each zone (room):

| Field | Required | Notes |
|---|---|---|
| Zone name | Yes | e.g. "Living Room", "Bedroom" |
| Room temperature sensor | Yes | `sensor.*` entity providing current room temp in °C |
| Window/door sensors | No | `binary_sensor.*` — open = window open → pause heat |
| TRV climate entities | No | `climate.*` entities to respect (not override) |

## Demo mode

Choose **Demo mode** in step 1 instead of the boiler connection. This creates:

- Simulated outdoor temperature, boiler flame/modulation/flow/return
- Two zones: **Living Room** and **Bedroom** (room temps evolve over time)
- No MQTT or real sensors required

Open the **Home Climate** sidebar item, set zones to **Heat**, and watch demand and flow setpoint change. Perfect for testing the UI before hardware work.

## After install

1. Open the **Home Climate** sidebar item (appears automatically after setup)
2. **Hard-refresh** the browser (Ctrl+Shift+R) after each update so the panel JS reloads
3. Open **Configure** on the integration to set outdoor fallback, duty cycle, schedule, occupancy, and gas settings

## Updating

**HACS:** HACS → Integrations → Home Climate Control → **Redownload** (or update when offered) → restart HA → hard-refresh the sidebar panel.

**Manual:** replace `custom_components/home_climate_control` with the new files → restart HA → hard-refresh.

## Troubleshooting

See [Troubleshooting](Troubleshooting.md) if the integration doesn't appear or the board can't connect.
