# Home Climate Control

**Smart weather-compensated heating that saves gas while keeping the house warm.**

Home Climate Control is a pair of projects that turn an ordinary gas boiler into a self-tuning, per-room heating system:

| Piece | What it is |
|---|---|
| **HCC** | A Home Assistant integration (this repo) — the brain. Reads every room's demand, computes the ideal boiler flow temperature, and drives the boiler on/off to burn as little gas as possible. |
| **HCS** | A tiny ESP32 firmware + OpenTherm adapter — the hands. It talks to the boiler over OpenTherm and to Home Assistant over MQTT. Repo: [ALeXXBody/home-climate-system](https://github.com/ALeXXBody/home-climate-system). |

Unlike a dumb thermostat or a fixed weather-compensation curve, HCC **learns your house**: how fast each room heats and cools, how laggy the radiators are, and how much the boiler should fire — then tunes itself to spend less gas and still hit your comfort times.

## In 60 seconds

1. **Install the HCC integration** in Home Assistant (via HACS).
2. **Flash the HCS firmware** onto an ESP32 wired to your boiler's OpenTherm port.
3. **Add rooms** and point each at its TRV (radiator valve) and a temperature sensor.
4. Done — the controller weather-compensates, condenses, duty-cycles, and (optionally) auto-tunes the curve for you.

## Where to go next

- **[What the app does](What-the-app-does)** — the full feature list and how each piece works.
- **[Installation](Installation)** — HACS + firmware + wiring.
- **[Configuration](Configuration)** — rooms, curve, flow and presets.
- **[Using the panel](Using-the-panel)** — what each tab/screen does.
- **[Gas optimization](Gas-optimization)** — the specifics of *why* this burns less gas.
- **[Troubleshooting](Troubleshooting)** — common questions and fixes.

---

*Home Climate Control is not just "another PID / Better-Thermostat clone" — the differentiator is the combination of per-room TRV demand, condensing control, duty-cycling, learned setbacks, optimal start and curve auto-tuning, all described in [Gas optimization](Gas-optimization).*
