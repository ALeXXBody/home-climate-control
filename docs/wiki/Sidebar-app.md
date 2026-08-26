# Sidebar app

After setup, **Home Climate** appears in the HA sidebar (thermometer-home icon). The app is a full-screen panel with live-updating data.

After any HCC update, **hard-refresh** the browser (Ctrl+Shift+R) to reload the panel JS.

## Header

Live **boiler link pill** in the top-right:

| Color | Meaning |
|---|---|
| Green | Boiler connected (HCS board online, MQTT responding) |
| Red | Boiler disconnected (no MQTT, wrong node ID, board offline) |
| Amber | Connection issue with diagnostic text from the board |

**Footer:** running integration version.

## Home tab

Overview of the heating system state:

| Display | Source |
|---|---|
| Outdoor temperature | Boiler OT sensor → HA fallback → stale boiler |
| Flow temperature | Current boiler flow water temp |
| Return temperature | Current boiler return water temp (if available) |
| Boiler modulation | Current burner % (0–100) |
| Flame status | ON/OFF |
| CH active | ON/OFF |
| Gas estimate | Current cost/kWh based on modulation or ΔT |
| Demand | Which rooms are calling for heat |

## Rooms tab

Per-room cards in single-row layout:

```
┌──────────────────────┬──────────────┬──────────────────┐
│ Room name            │   [thermo]   │ Mode  [Edit] [⚙] │
│ 21.3 °C  ↑ warming  │   21.5 °C    │ Comfort  ▼       │
└──────────────────────┴──────────────┴──────────────────┘
```

| Left panel | Center | Right panel |
|---|---|---|
| Room name, current temp, trend arrow | Thermostat dial (target temp) | Mode/Profile dropdown, Edit button, Calibrate button |

**Trend arrows:** ↑ warming · ↓ cooling · — stable

**Mode/Profile options:**
- **Off** — zone disabled
- **Heat** — active, following target temperature
- **Eco / Comfort / Night / Away** — smart preset (learned setback depths)
- **Auto** — follows HA schedule (if configured)

**Insights panel** (expandable on each card):
- Warm rate (°C/h) — how fast the room heats up
- Dead time (min) — delay before temp starts rising
- Pre-heat lead (min) — optimal start calculation
- Setback learned depth (°C) — how much the room can setback at night

## Devices tab

Board management:

- **Board selector** — choose which HCS board to control (if multiple on MQTT)
- **Live controls** — replica of the board's web UI:
  - CH on/off, DHW on/off
  - Flow setpoint, DHW setpoint
  - Max modulation slider
  - Weather compensation toggle + curve config
  - Failsafe config (enable, flow, grace period)
- **Firmware catalog** — lists available releases from GitHub
- **OTA flash** — select a board, pick a firmware version, flash over the air with progress indicator
- **Settings sync** — reads and writes board settings via MQTT (two-way)

## Diagnostics tab

Internal system state for debugging and tuning:

### Heating curve
- Current outdoor→flow mapping
- Outdoor temperature source (boiler / HA fallback / none)
- Auto-tune status and current coefficient

### Setbacks
- Per-room learned night/away depth
- Per-room warm rate and dead time
- Calibration status

### Duty cycle
- Current phase (ON/OFF) and remaining time
- Cycle period (adapts to outdoor load)
- Active status (enabled, below min modulation, etc.)

### Schedule
- Current schedule entity and type (schedule/input_select/sensor)
- Current state (on/off/preset name)
- Active preset on each room

### Occupancy
- Current presence state (home/away)
- Last presence change
- Assigned preset per room
- Tracker entities and their states

### Gas estimate
- Current estimation mode (modulation / ΔT / hydronic kW)
- ΔT values (flow - return)
- Current modulation %
- Nameplate and calibration values
- Estimated gas flow rate and total

### Pre-heat & dead-time
- Per-room dead time (minutes)
- Per-room warm rate (°C/h)
- Current lead calculation
- Whether pre-heat is active
