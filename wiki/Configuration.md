# Configuration

## Rooms (zones)

Each room is a "zone". For each room you configure:

| Field | Meaning |
|---|---|
| **Name** | Display name (also the climate entity name). |
| **TRV entity** | The radiator valve's climate entity (`climate.office_trv` …). HCC reads its target + demand. |
| **Temperature sensor** | Where HCC reads the room's actual temperature (falls back to the TRV's own reading if empty). |
| **Floor** | Ground / first / … for the floor-plan view. |
| **Heat control** | **Smart** (HCC controls it) vs **Manual** (HCC just observes — the TRV does its own thing). |

> A room needs at least a TRV *or* a temperature sensor to participate. Rooms without a TRV can still be observed.

## The heating curve

The three numbers that shape weather compensation:

| Setting | Default | Meaning |
|---|---|---|
| **Min flow** | 25 °C | The flow floor. |
| **Max flow** | 75 °C | The flow ceiling. |
| **Curve coefficient** | 1.2 | How steeply flow rises as outdoor temperature falls. Higher = hotter radiators on cold days. |

Tuning rule of thumb: on a cold day, if rooms are slow to warm → raise the coefficient slightly; if rooms overshoot → lower it. **Auto-tune** does this for you automatically (see below).

## Presets

Four absolute temperatures, applied to *all* smart rooms at once:

- **Comfort** (default 21 °C) — normal living temperature.
- **Eco** (19 °C) — mild setback.
- **Away** (16 °C) — deep setback for when you're out.
- **Boost** — a temporary high target.

## Schedules & occupancy

- **Heating schedule**: point it at an HA `schedule.*`, `input_select`, or sensor to drive presets on a timetable.
- **Occupancy**: phone/person trackers switch rooms to *Away* when everyone leaves, *Home* when someone returns.

## Auto-Optimize (gas optimizers)

The **Auto-Optimize** master switch enables HCC to *write* automatic adjustments. With it on:

- **Auto-tune curve** — slowly adjusts the coefficient to your house.
- **Auto-cap max flow** — trims the flow ceiling when the return is hot.
- **Auto-balance TRV** (opt-in) — re-balances valve limits per room.

These are ON by default (curve auto-tune + flow cap); TRV balancing is opt-in.

## Boiler & gas

- **Boiler min modulation** — the lowest continuous fire the boiler can hold (nameplate); drives duty-cycling.
- **Rated heat input (kW)** — converts modulation % into gas kWh for the statistics.
- **Gas price per kWh** — optional, adds cost to the statistics.

---

Next: [Using the panel](Using-the-panel).
