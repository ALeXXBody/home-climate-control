# Home Climate Control

Private Home Assistant custom component. MIT license planned for public release.

**Goal:** multi-zone climate control that respects room/TRV heat requests while
minimising gas use via OpenTherm weather compensation and the lowest workable
flow temperature.

## Status

Phase 1 MVP skeleton (v0.1.0):

- Config flow: OTGW MQTT prefix + node id, flow limits, curve coefficient, zones
- Zone climate entities (presets, window pause, TRV demand respect)
- Central controller: weather-compensated heating curve + PID flow boost
- Boiler backend: OTGW-firmware MQTT (`ctrlsetpt` / `chenable` / telemetry)

Not yet: low-load duty cycling, auto-tune, underfloor profiles, diagnostics
sensors UI, HACS packaging polish.

## Install (dev)

1. Copy `custom_components/home_climate_control` into your HA config directory.
2. Ensure the MQTT integration is configured and OTGW-firmware is publishing.
3. Restart Home Assistant → Settings → Devices & services → Add integration
   → **Home Climate Control**.
4. Enter MQTT top topic (default `OTGW`), node id (e.g. `otgw-AABBCCDDEEFF`),
   then add at least one zone (room temperature sensor).

Outdoor temperature is taken from the boiler outdoor sensor published by OTGW
as `outsidetemperature`.

## Docs

- [Research (SAT / Better Thermostat / Versatile Thermostat + licenses)](docs/research.md)
- [Architecture](docs/architecture.md)

## License

MIT (see `LICENSE`). Repository stays private until ready for public release.
