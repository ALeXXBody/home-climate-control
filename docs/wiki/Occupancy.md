# Occupancy (phone presence)

> **Off by default.** Enable only after selecting tracker entities.

## What it does

When enabled, HCC monitors phone trackers (or other presence sensors) and automatically switches room presets:

- **All away** → away preset on every smart room
- **Anyone home** → home preset (or live schedule preset if a schedule is configured)

## Setup

1. Go to **Settings → Devices & services → Home Climate Control → Configure**
2. Turn **Occupancy auto-setback** **on**
3. Select one or more **Presence entities**:
   - `device_tracker.*` — phone/device trackers (e.g. HA companion app, Router-based)
   - `person.*` — HA person entities
   - `binary_sensor.*` — any presence binary sensor
4. Set **Occupancy away preset** (default: `away`)
5. Set **Occupancy home preset** (default: `comfort`)
6. Click **Submit**

## Behaviour

### Away mode
When **all** selected trackers report not-home/away:
- Every smart room gets the **away preset** (e.g. `away` = deep setback)
- Optimal-start pre-heat calculates lead time to recover before you arrive home
- Manual override is **not** applied during away

### Home mode
When **any** selected tracker reports home:
- Each room gets the **home preset** — but with priority:
  1. If a **schedule** is configured and the current window is active → use the schedule's preset
  2. Otherwise → use the **home preset** (e.g. `comfort`)
- This means schedule takes precedence over occupancy when you're home

### Sticky override
If you manually change a room's preset while home (e.g. switch from comfort to eco):
- That manual choice stays until the **next occupancy change** (everyone leaves or schedule window changes)
- Occupancy does **not** immediately override your manual selection

## Diagnostics

The **Diagnostics** tab shows occupancy state when enabled:

| Field | Meaning |
|---|---|
| Presence state | `home` / `away` / `unavailable` |
| Last change | When the last presence transition happened |
| Assigned preset per room | Which preset was applied to each room |

## Important notes

- **Enable occupancy only after selecting trackers** — turning it on without entities does nothing
- **Minimum 2 trackers recommended** for reliable away detection (1 phone = never "all away" when at home)
- Occupancy and schedule work together: schedule drives when you're home, occupancy handles when you're away
- The system does **not** geo-fence or track location — it only reads on/off home state
