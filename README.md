# Home Climate Control

Private Home Assistant custom component for multi-zone heating control.

**Goal:** respect room and TRV heat requests while minimising gas use via
OpenTherm weather compensation and the lowest workable flow temperature.

Repository: https://github.com/ALeXXBody/home-climate-system (private)

## Requirements

- Home Assistant 2024.1 or newer
- [HACS](https://hacs.xyz/) (recommended)
- MQTT integration configured in Home Assistant
- OpenTherm Gateway running [OTGW-firmware](https://github.com/rvdbreemen/OTGW-firmware) with MQTT enabled
- Boiler outdoor temperature sensor (used for weather compensation)

## Install via HACS (custom repository)

Because this repo is private, install it as a **custom repository** in HACS.

### 1. Add the repository in HACS

1. Open **HACS** in Home Assistant.
2. Open the three-dot menu (⋮) in the top right → **Custom repositories**.
3. Fill in:
   - **Repository:** `https://github.com/ALeXXBody/home-climate-system`
   - **Category:** `Integration`
4. Click **Add**.

> If HACS cannot see a private repo, connect a GitHub account that has access:
> HACS → three-dot menu → **GitHub** (or re-authenticate HACS with a token
> that can read this repository).

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

## Status (v0.1.0)

- Config flow: OTGW MQTT prefix + node id, flow limits, curve coefficient, zones
- Zone climate entities (presets, window pause, TRV demand respect)
- Central controller: weather-compensated heating curve + PID flow boost
- Boiler backend: OTGW-firmware MQTT (`ctrlsetpt` / `chenable` / telemetry)

Not yet: low-load duty cycling, auto-tune, underfloor profiles, diagnostics sensors UI.

## Docs

- [Research (SAT / Better Thermostat / Versatile Thermostat + licenses)](docs/research.md)
- [Architecture](docs/architecture.md)

## License

MIT (see [`LICENSE`](LICENSE)). Repository stays private until ready for public release.
