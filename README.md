# Home Climate Control

Home Assistant custom component for multi-zone heating control that minimises gas use.

**Software** (this repo) · companion **hardware/firmware**:  
[home-climate-system](https://github.com/ALeXXBody/home-climate-system)

**Docs wiki:** [Home · Install · Options · Tiers · FAQ](docs/wiki/Home.md)  
*(Same pages live under `docs/wiki/`. To mirror on GitHub Wiki: repo → Wiki → create Home, paste from `docs/wiki/`.)*

**Goal:** respect room and TRV heat requests while minimising gas use via OpenTherm
weather compensation, learned behaviour, and the lowest workable flow temperature.

| | |
|---|---|
| **Repo** | https://github.com/ALeXXBody/home-climate-control |
| **Current version** | v1.4.5 |
| **Domain** | `home_climate_control` |
| **License** | MIT |

## Naming

| Name | What it is |
|---|---|
| **Home Climate Control (HCC)** | This software — HA custom integration + sidebar app |
| **Home Climate System (HCS)** | Hardware + ESP boiler-gateway firmware ([separate repo](https://github.com/ALeXXBody/home-climate-system)) |

## Features

### Control core

- **Weather-compensated heating curve** — flow tracks outdoor temp; lowest workable curve wins
- **Outdoor source priority** — boiler outdoor (fresh) → optional HA sensor/weather fallback → stale boiler
- **PID flow boost** with anti-windup when rooms lag
- **Auto-tuning heating curve** — learns coefficient from real comfort error
- **Smart setbacks** — night/away depth learned **per room** from recovery speed
- **Dead-time learning + optimal-start** — `lead = dead_time + deficit/warm_rate`; reactive pre-heat on away/eco when catch-up would miss the window
- **Low-load duty cycling** — when demand &lt; boiler min modulation, PWM CH with long on/off slices (configurable)
- **CycleGuard** — adaptive burner rest + minimum-on floor
- **Condensing pull-down** — shaves flow when OpenTherm return is above ~54 °C (comfort first)
- **Load-aware health flags** — “struggling” patience scales with outdoor load (fewer cold-day false alarms)
- **Slope open-window detection** — pause heat on abnormal cool-down without contact sensors
- **Bootstrap calibration** — one click measures °C/h warm-up and seeds the setback learner
- **Insulation score** — weather-normalized heat-loss label per room
- **Training-data logger** — minute JSONL under `<config>/home_climate_training/` (survives updates)

### Schedules & occupancy (optional — Settings)

- **HA schedule → presets** — `schedule.*` ON/OFF (or `input_select`/`sensor`) drives room presets; manual override sticky until next window
- **Phone occupancy** — opt-in: `device_tracker` / `person` / presence sensors; all away → away preset; anyone home → home preset or live schedule

### Metering & diagnostics

- **Estimated gas** — modulation × time, or **flow/return ΔT** when mod is missing (`P_max × ΔT/20K / η`)
- Boiler MemberID make/model detection
- Custom 1-Wire probes with roles

### Boards & OTA

- Board tab — live replica of the ESP Control page
- Two-way settings sync (firmware v1.2+)
- Firmware tab — GitHub catalog, LAN mirror, OTA progress + post-reboot success

### Zones — house model

- **Floor** + **heater control**: ⚡ smart TRV · ✋ manual (observe only)
- Floor-grouped room cards; edit/add/remove from the panel
- Window sensors; multi-window OR; TRV demand respect

## Requirements

- Home Assistant 2024.1+
- [HACS](https://hacs.xyz/) (recommended)
- MQTT in Home Assistant
- A **Home Climate System** board ([repo](https://github.com/ALeXXBody/home-climate-system))
- Outdoor temp (boiler sensor and/or HA fallback)

## Install via HACS

1. HACS → ⋮ → **Custom repositories** →  
   `https://github.com/ALeXXBody/home-climate-control` · Category **Integration**
2. Download **Home Climate Control** → restart HA
3. **Settings → Devices & services → + Add integration** → Home Climate Control  
   - HCS: MQTT prefix + node id, flow limits, curve  
   - Or **Demo mode** (no hardware)

### Options (after install)

**Configure** the integration to set:

| Option | Default |
|---|---|
| Outdoor temperature fallback | — |
| Boiler min modulation % | 20 |
| Low-load duty cycling | on |
| Heating schedule entity | — |
| Schedule on/off presets | comfort / eco |
| **Occupancy auto-setback** | **off** |
| Presence trackers | — |
| Occupancy away/home presets | away / comfort |
| Gas nameplate kW, calibration, price | … |

## Update

HACS → Home Climate Control → update → restart HA → hard-refresh the sidebar panel (Ctrl+Shift+R).

## Sidebar app

| Tab | Content |
|---|---|
| Home | Outdoor / flow / demand / gas |
| Rooms | Thermostat cards, insights (lead, dead-time, pre-heat) |
| Devices | Board control + firmware OTA |
| Diagnostics | Curve, duty cycle, schedule, occupancy, setbacks, gas ΔT |

## Efficiency roadmap (tiers)

| Tier | Status (v1.4.5) |
|---|---|
| **0** room temp + boiler | Calibration, dead-time + pre-heat, duty cycle, CycleGuard, open-window, health, gas est. |
| **0b** + outdoor | Curve, outdoor fallback, load-aware health, condensing pull-down |
| **1** internet/API | Schedule → presets |
| **2** phones / contacts | Occupancy (optional), window contacts |
| **3–4** extra sensors / OT depth | CO₂ volume, lux, true radiator watts, balancing — later |

## Status

- Backends: demo · native HCS MQTT  
- Tests: `pytest` in repo (278+ at 1.4.5)  
- Companion firmware: [HCS v1.4.0](https://github.com/ALeXXBody/home-climate-system/releases/tag/v1.4.0)

## Run tests

```bash
cd /path/to/home-climate-control
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q
```

## Docs

- **[Docs wiki](docs/wiki/Home.md)** — [Install](docs/wiki/Install.md) · [Options](docs/wiki/Options-and-settings.md) · [Tiers](docs/wiki/Efficiency-tiers.md) · [FAQ](docs/wiki/FAQ.md)  
- [Architecture](docs/architecture.md) · [Research](docs/research.md) · [Audit 1.4.0](docs/AUDIT-1.4.0.md)  
- Firmware: [home-climate-system](https://github.com/ALeXXBody/home-climate-system) · [HCS docs wiki](https://github.com/ALeXXBody/home-climate-system/blob/main/docs/wiki/Home.md)

## Support

[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-ffdd00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/alexxbody)

## License

MIT — see [`LICENSE`](LICENSE).
