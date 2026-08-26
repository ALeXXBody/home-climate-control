# Schedule → presets

Connect an HA schedule to drive room presets automatically.

## Supported entity types

| Type | How it works |
|---|---|
| `schedule.*` | ON/OFF windows → on-preset / off-preset |
| `input_select.*` | State **is** the preset name (e.g. `eco`, `comfort`, `away`) |
| `sensor.*` | State **is** the preset name (e.g. `comfort`, `night`) |

## Setup

1. Go to **Settings → Devices & services → Home Climate Control → Configure**
2. Set **Heating schedule entity** to your `schedule.*`, `input_select.*`, or `sensor.*`
3. For `schedule.*`: set **Schedule on preset** (default: `comfort`) and **Schedule off preset** (default: `eco`)
4. Click **Submit**

## How each type works

### schedule.* (recommended)

HA's built-in `schedule` entity has time windows that are either ON or OFF:

| Window state | Preset applied |
|---|---|
| ON | `schedule on preset` (default: comfort) |
| OFF | `schedule off preset` (default: eco) |

**Example:** Schedule ON 06:00–22:00 = comfort, OFF 22:00–06:00 = eco.

The schedule preset applies to every smart room that doesn't have an active manual override.

### input_select.* / sensor.*

The entity's current state is treated as a preset name directly:

| State | What happens |
|---|---|
| `comfort` | Applies `comfort` preset to all smart rooms |
| `eco` | Applies `eco` preset |
| `away` | Applies `away` preset |
| `night` | Applies `night` preset |
| Any other value | Matched against HA aliases (`home` → `comfort`, etc.) |

This lets you use **any** automation or dashboard button to change presets — just set the input_select/sensor to the preset name.

## Sticky manual override

When the schedule changes preset:
- All smart rooms follow the new preset
- If you **manually** change a room (e.g. switch from comfort to eco via the room card):
  - That manual choice **sticks** until the next schedule change or occupancy transition
  - The schedule does **not** immediately override your manual selection

This means you can temporarily adjust a room without fighting the schedule.

## Interaction with occupancy

| Presence | Schedule | Room gets |
|---|---|---|
| Away | Any | Away preset (occupancy wins) |
| Home | Active window | Schedule's on-preset |
| Home | Inactive window | Schedule's off-preset |
| Home | None configured | Home preset from occupancy |

## Preset aliases

HCC maps common names to internal presets:

| Alias | Maps to |
|---|---|
| `home` | comfort |
| `sleep`, `bedtime` | night |
| `frost` | away (shallow) |
| `standby` | eco |

## Tips

- Use `input_select` on your dashboard for manual preset switching that the schedule can override
- Schedule + occupancy is the most common setup: schedule drives daytime, occupancy handles absence
- Check the **Diagnostics** tab to see which schedule is active and what preset is assigned
