# Install

## HACS (recommended)

1. HACS → ⋮ → **Custom repositories**
2. URL: `https://github.com/ALeXXBody/home-climate-control` · Category: **Integration**
3. Download **Home Climate Control** → **Restart Home Assistant**
4. **Settings → Devices & services → + Add integration** → Home Climate Control

### Setup wizard

**HCS backend**

- MQTT topic prefix (default `hcs`)
- Board node id (e.g. `hcs-aabbccddeeff` from serial / discovery)
- Min / max flow temperature, curve coefficient

**Demo backend** — no MQTT or hardware; two simulated rooms.

## Manual install

Copy `custom_components/home_climate_control` into your HA `config/custom_components/` folder → restart → add integration as above.

## After install

1. Open the **Home Climate** sidebar item  
2. Hard-refresh the browser (Ctrl+Shift+R) after each update so the panel JS reloads  
3. Open **Configure** on the integration for outdoor fallback, duty cycle, schedule, occupancy  

## Firmware

Flash boards from [home-climate-system releases](https://github.com/ALeXXBody/home-climate-system/releases) or HCC **Devices** tab OTA. Prefer firmware **≥ 1.4.0**.
