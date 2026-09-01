# Home Climate Control — Wiki

Home Climate Control (HCC) is a Home Assistant custom integration for **multi-zone gas heating control** that minimises gas use.

| | |
|---|---|
| **Repo** | [github.com/ALeXXBody/home-climate-control](https://github.com/ALeXXBody/home-climate-control) |
| **Current version** | v1.5.5 |
| **Companion firmware** | [Home Climate System (HCS)](https://github.com/ALeXXBody/home-climate-system) — [HCS Wiki](https://github.com/ALeXXBody/home-climate-system/blob/main/docs/wiki/Home.md) |
| **License** | MIT |

## What it does

HCC creates a **climate entity per room** and drives an OpenTherm boiler gateway ([HCS board](https://github.com/ALeXXBody/home-climate-system)) over MQTT. It respects room and TRV heat requests while minimising gas use through:

- **Weather-compensated flow temperature** — outdoor temp drives a heating curve; the lowest workable curve wins via auto-tune
- **Learned setbacks** — night/away depth learned per room from real recovery speed
- **Dead-time learning + optimal-start pre-heat** — calculates exactly when to start warming so rooms are comfortable on time
- **Low-load duty cycling** — PWMs the boiler when demand is below its minimum modulation
- **Condensing pull-down** — shaves flow when return temp is above ~54 °C to stay in condensing mode
- **Load-aware health flags** — patience scales with outdoor load (fewer cold-day false alarms)
- **CycleGuard** — adaptive burner rest + minimum-on floor prevents short-cycling
- **Slope open-window detection** — pauses heat on abnormal cool-down without contact sensors
- **Bootstrap calibration** — one click measures °C/h warm-up and seeds the setback learner
- **Estimated gas** — modulation-based or flow/return ΔT-based accounting

## Optional features (Settings)

- **HA schedule → presets** — `schedule.*` ON/OFF (or `input_select`/`sensor`) drives room presets
- **Phone occupancy** — `device_tracker` / `person` presence; all away → away preset

## Pages

| Page | What's in it |
|---|---|
| [Install](Install.md) | HACS, manual, setup wizard, demo mode |
| [Quick start](Quick-start.md) | First 10 minutes after install |
| [Options & settings](Options-and-settings.md) | Every configurable option, what it does, defaults |
| [Sidebar app](Sidebar-app.md) | All tabs: Home, Rooms, Devices, Diagnostics |
| [Occupancy](Occupancy.md) | Phone tracker setup, away/home presets, sticky override |
| [Schedule → presets](Schedule.md) | HA schedule, input_select, sensor integration |
| [Efficiency tiers](Efficiency-tiers.md) | Tier 0–4 roadmap with requirements |
| [Calibration & setbacks](Calibrate-and-setbacks.md) | Bootstrap cal, dead-time, optimal start, warm rate |
| [Gas metering](Gas-metering.md) | Modulation vs ΔT estimate, nameplate, hydronic kW |
| [Failsafe & CycleGuard](Failsafe-and-CycleGuard.md) | Connection-loss protection, short-cycle prevention |
| [FAQ](FAQ.md) | Common questions |
| [Troubleshooting](Troubleshooting.md) | Issues and fixes |

## Requirements

- Home Assistant 2024.1+
- [HACS](https://hacs.xyz/) (recommended)
- MQTT in Home Assistant
- A **Home Climate System** board ([repo](https://github.com/ALeXXBody/home-climate-system))
- Outdoor temperature (boiler sensor and/or HA fallback)
