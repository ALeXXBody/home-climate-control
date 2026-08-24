# Home Climate Control

Home Assistant custom component for multi-zone heating control that minimises gas use.

**Software** (this repo) · companion **hardware/firmware**:  
[home-climate-system](https://github.com/ALeXXBody/home-climate-system)

**Goal:** respect room and TRV heat requests while minimising gas use via OpenTherm
weather compensation, learned behaviour, and the lowest workable flow temperature.

| | |
|---|---|
| **Repo** | https://github.com/ALeXXBody/home-climate-control |
| **Current version** | v1.1.1 |
| **Domain** | `home_climate_control` |
| **License** | MIT |

## Naming

| Name | What it is |
|---|---|
| **Home Climate Control** | This software — HA custom integration + sidebar app |
| **Home Climate System** | Hardware + ESP32/ESP8266 boiler-gateway firmware (separate repo) |

## Features

### Control core

- **Weather-compensated heating curve** — flow setpoint tracks outdoor temperature;
  lowest workable curve wins
- **PID flow boost** with anti-windup when rooms lag behind schedule
- **Auto-tuning heating curve** — learns the comfort-driven coefficient from real
  recovery behaviour instead of manual trial-and-error
- **Smart setbacks** — night/Away setbacks learn *per room* how fast it recovers,
  so pre-heat lead time is calculated, not guessed
- **CycleGuard** — adaptive burner rest window + minimum-on floor; protects the
  boiler from short-cycling at low load

### Metering & diagnostics

- **Estimated gas accounting** from boiler telemetry (modulation × time) — no gas
  meter required
- **Boiler auto-detection** — reads the OpenTherm MemberID and identifies make/model
- **Custom 1-Wire probes** — auto-detected DS18B20 sensors exposed as selectable
  HA entities with user-defined roles

### Boards & OTA

- **Board tab** — live two-way replica of the ESP Control page inside the sidebar app
  (CH/DHW toggles, DHW setpoint, flow setpoint, max-modulation slider)
- **Two-way settings sync** with boards running firmware v1.2.0+
- **Firmware tab** — dynamic catalog tracking GitHub releases; sha256-verified
  self-refreshing LAN mirror; OTA progress bar, failure notifications and
  post-reboot success detection

### Zones

- Zone climate entities with presets, heat/off
- Window/door sensor pause
- TRV demand respect — zones only call for heat when their TRVs actually ask

## Requirements

- Home Assistant 2024.1 or newer
- [HACS](https://hacs.xyz/) (recommended)
- MQTT integration configured in Home Assistant
- One of:
  - **OpenTherm Gateway** with MQTT (e.g. OTGW-firmware), or
  - a **Home Climate System** board (DIYLess OT shield + ESP8266/ESP32, see the
    [home-climate-system](https://github.com/ALeXXBody/home-climate-system) repo)
- Boiler outdoor temperature sensor (weather compensation)

## Install via HACS (custom repository)

### 1. Add the repository in HACS

1. Open **HACS** in Home Assistant.
2. Open the three-dot menu (⋮) in the top right → **Custom repositories**.
3. Fill in:
   - **Repository:** `https://github.com/ALeXXBody/home-climate-control`
   - **Category:** `Integration`
4. Click **Add**.

### 2. Download the integration

1. In HACS go to **Integrations**.
2. Search for **Home Climate Control**.
3. Open it → **Download** → confirm.
4. When prompted, **restart Home Assistant**.

### 3. Add the integration

1. Go to **Settings → Devices & services**.
2. Click **+ Add integration**.
3. Search for **Home Climate Control**.
4. Complete the setup wizard:
   1. **Boiler / OTGW**
      - MQTT top topic (default `OTGW`)
      - OTGW node id (e.g. `otgw-AABBCCDDEEFF`)
      - Min / max flow temperature
      - Heating curve coefficient
   2. **Zones** (at least one)
      - Zone name
      - Room temperature sensor
      - Optional window/door sensors
      - Optional TRV climate entities

Outdoor temperature is read from the boiler outdoor sensor published by OTGW
as `outsidetemperature`.

## Manual install (without HACS)

1. Clone or download this repository.
2. Copy the folder  
   `custom_components/home_climate_control`  
   into your Home Assistant config directory, so you have:  
   `config/custom_components/home_climate_control/`
3. Restart Home Assistant.
4. Continue from **Add the integration** above  
   (**Settings → Devices & services → + Add integration**).

## Update

**HACS:** HACS → Integrations → Home Climate Control → **Redownload** (or update when offered) → restart HA.

**Manual:** replace `custom_components/home_climate_control` with the new files → restart HA.

## Sidebar app

After the integration is set up, a **Home Climate** item appears in the Home Assistant
sidebar (icon: thermometer home). Full-screen UI:

| Tab | Content |
|---|---|
| Overview | Boiler / outdoor / flow / demand + zone summary |
| Zones | Set temperature, heat/off, presets |
| Board | Live control of a connected HCS board (replica of its web UI) |
| Firmware | Catalog, mirror status, flash boards over-the-air with progress |
| Settings | Curve / flow limits, boiler info, board settings |

The panel footer shows the running integration version.

## Demo mode (no hardware)

When adding the integration, choose **Demo OTGW**. That creates:

- Simulated outdoor temperature, boiler flame / modulation / flow / return
- Two zones: **Living Room** and **Bedroom** (room temps evolve over time)
- No MQTT or real sensors required

Then open the **Home Climate** sidebar, set zones to **Heat**, and watch demand
and flow setpoint change. Perfect for testing the UI before hardware work.

## Status (v1.1.1)

- Backends: demo simulator · OTGW-firmware MQTT · native HCS board (MQTT)
- Control: heating curve + auto-tune · PID flow boost · smart setbacks · CycleGuard
- Metering: estimated gas accounting · boiler MemberID detection · 1-Wire probe entities
- Boards: live Board tab · two-way settings sync · OTA with progress/success detection

Planned next: per-room heat-rate calibration (°C/h room models), temp-slope
open-window detection, floor plan view.

## Run tests (local venv)

```bash
cd /path/to/home-climate-control
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest -v
```

## Docs

- [Research (third-party thermostats + licenses)](docs/research.md)
- [Architecture](docs/architecture.md)
- Hardware/firmware: [home-climate-system](https://github.com/ALeXXBody/home-climate-system)

## Support

If this project helps you, you can support development here:

[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-ffdd00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/alexxbody)

https://buymeacoffee.com/alexxbody

## License

MIT (see [`LICENSE`](LICENSE)).
