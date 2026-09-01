# HACS default — draft PR text

Ready to submit when community traction is there (aim ~50+ installs/stars).
**Open a PR against:** https://github.com/hacs/default — add the repo under
`integration` in `repositories.yaml` (alphabetical order).

**PR title:** `Add ALeXXBody/home-climate-control to integration category`

---

**PR body:**

## Proposed repository

| | |
|---|---|
| Repository | https://github.com/ALeXXBody/home-climate-control |
| Category | `integration` |
| Domain | `home_climate_control` |
| Description | Multi-zone gas heating control for OpenTherm boilers: weather-compensated flow temperature, learned setbacks, optimal-start pre-heat, low-load duty cycling, estimated gas metering — paired with the [Home Climate System](https://github.com/ALeXXBody/home-climate-system) ESP32/ESP8266 boiler gateway. |

## Default criteria checklist

- **Actively maintained** — continuous releases since 2024; current version v1.5.3 with tagged, semver GitHub releases and release notes for every change.
- **Tested** — 283 unit tests in CI-runnable pytest suite; firmware companion repo ships 58 native tests and 8 board builds.
- **Documented** — full user wiki under `docs/wiki/` (install, options, occupancy, schedule, efficiency tiers, FAQ, troubleshooting); README with screenshots captured from the live panel.
- **HA standards** — manifest with `version` + `iot_class`, config/option flows, `RestoreEntity` for user state, WebSocket API under the integration domain, inline `brand/` assets (HA 2026.3+ mechanism, no `home-assistant/brands` PR needed).
- **Quality gates** — `hacs/action` validation passes; no core patches, no theme hacks; MQTT-based transport using the public `mqtt` integration.
- **Community interest** — (fill in current numbers before submitting: HACS installs, GitHub stars, forum thread link).

## Notes

- Companion firmware repo (`home-climate-system`) is intentionally separate: hardware/firmware vs HA integration. HCC's built-in **Firmware** tab OTA-updates boards from its GitHub catalog.
- No other HACS integration covers this niche: OpenTherm boiler-gateway control (DIYLess/HCS hardware) with multi-zone setpoint learning and gas-use estimation.

---

## Pre-submission todo (do these first, in order)

1. **Traction**: publish a showcase post (Home Assistant community forum + r/homeassistant) with the screenshots from `docs/screenshots/`; link the forum thread in this PR.
2. **Numbers**: after ~2–4 weeks, fill in installs (HACS shows them in the repo card) and star count.
3. **Fork `hacs/default`**, add `ALeXXBody/home-climate-control` under the `integration:` section of `repositories.yaml`, keep alphabetical order.
4. **Open the PR** with the checklist above; sign off, watch for hacsbot feedback (it usually asks for the domain/category confirmation and criteria links).
