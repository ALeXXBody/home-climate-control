# Home Climate Control

Home Assistant custom component for multi-zone heating control.

**Software** (this repo) · companion **hardware/firmware**:  
[home-climate-system](https://github.com/ALeXXBody/home-climate-system)

**Goal:** respect room and TRV heat requests while minimising gas use via
OpenTherm weather compensation and the lowest workable flow temperature.

| | |
|---|---|
| **Repo** | https://github.com/ALeXXBody/home-climate-control |
| **Domain** | `home_climate_control` |
| **License** | MIT |

## Naming

| Name | What it is |
|---|---|
| **Home Climate Control** | This software — HA custom integration |
| **Home Climate System** | Hardware + ESP32/ESP8266 firmware (separate repo) |

## Requirements

- Home Assistant 2024.1 or newer
- [HACS](https://hacs.xyz/) (recommended)
- MQTT integration configured in Home Assistant
- OpenTherm Gateway with MQTT (e.g. OTGW-firmware), **or** later a Home Climate System device
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
sidebar (icon: thermometer home). Full-screen UI for:

| Tab | Status |
|---|---|
| Overview | Boiler / outdoor / flow / demand + zone summary |
| Zones | Set temperature, heat/off, presets |
| Floor plan | Placeholder (coming later) |
| Firmware | Placeholder (HCS device flash later) |
| Settings | Curve / flow limits (read-only; edit via Configure) |

## Demo mode (no hardware)

When adding the integration, choose **Demo OTGW**. That creates:

- Simulated outdoor temperature, boiler flame / modulation / flow / return
- Two zones: **Living Room** and **Bedroom** (room temps evolve over time)
- No MQTT or real sensors required

Then open the **Home Climate** sidebar, set zones to **Heat**, and watch demand
and flow setpoint change. Perfect for testing the UI before firmware/board work.

## Status (v0.3.0)

- Config flow: **Demo OTGW** or real OTGW MQTT
- Zone climate entities (presets, window pause, TRV demand respect)
- Central controller: weather-compensated heating curve + PID flow boost
- Boiler backends: demo simulator + OTGW-firmware MQTT
- **Sidebar panel** + WebSocket API (`home_climate_control/get_status`, `set_zone`)

Not yet: low-load duty cycling, auto-tune, underfloor profiles, floor plan, firmware flasher,
native Home Climate System device backend.

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
