# Research: Existing Thermostat Projects

Date: 2026-08-22. Goal: understand what SAT, Better Thermostat and Versatile
Thermostat do, check licenses, and define what Home Climate Control (HCC)
should be.

## 1. License analysis (critical)

| Project | Repo | License | Code reusable in HCC (MIT)? |
|---|---|---|---|
| SAT – Smart Autotune Thermostat | Alexwijn/SAT | GPL-3.0 | **NO** – study ideas only, clean-room implementation |
| Better Thermostat | KartoffelToby/better_thermostat | AGPL-3.0 | **NO** – strictest; no code copying at all |
| Versatile Thermostat | jmcollin78/versatile_thermostat | MIT | **YES** – free to reuse with attribution |

Consequence: all SAT/BT-inspired features must be implemented from scratch
(algorithms and concepts are not copyrightable; source code is). VT code may
be adapted directly. This keeps HCC publishable under MIT later.

## 2. What each project does

### SAT (GPL-3.0) — boiler-side brain, deep OpenTherm integration
Talks directly to the boiler through an OpenTherm Gateway (OTGW via
MQTT/serial), DIYLess shield, Ihor Melnyk adapter, or ESPHome `opentherm`.

Core ideas worth copying (concept-level only):
- **Weather compensation**: computes boiler flow-water setpoint from a
  heating curve `flow = f(outdoor_temp, room_setpoint)`. Curves: Classic,
  Quantum, Precision — separate variants for radiators vs underfloor.
- **PID control of room temp** with automatic gains: gains scale with the
  heating-curve coefficient / outdoor temp (mild in warm weather, aggressive
  in cold). Adaptive controller option auto-tunes continuously.
- **Autotune calibration (~20 min)**: sends max-modulation=0 and flow=75 to
  find the highest flow temperature the boiler can hold at 0% modulation →
  "Overshoot Protection Value" (OPV).
- **Low-load control / overshoot protection**: when required power < boiler
  minimum modulation, avoid cycling by computing boiler on/off times from
  OPV; automatic duty cycle extends cycles up to 30 min in mild weather.
- **Multi-room ("Areas")**: primary physical thermostat is synced
  (setpoint + hvac_action mirrored, works as HA-failure backup); rooms are
  TRV climate entities — if any room calls for heat, boiler starts.
  - Heating mode *Comfort*: PID error = max error across rooms.
  - Heating mode *Eco*: PID error = main thermostat's error only.
- **Return-temp adjustment factor** (experimental): lowers control setpoint
  based on boiler return water temperature (condensing efficiency).
- Gas consumption estimation from min/max boiler consumption values;
  DHW setpoint control; open-window detection; humidity-based perceived
  temperature (Summer Simmer Index).
- Scale reference: ~45 python modules (boiler.py, heating_curve.py,
  overshoot_protection.py, minimum_setpoint.py, per-manufacturer modules,
  mqtt/opentherm.py, mqtt/ems.py, area.py...).

### Better Thermostat (AGPL-3.0) — TRV wrapper / corrector
Wraps existing TRV climate entities; does not talk to the boiler.

Core ideas:
- Use a remote room sensor instead of the TRV's near-radiator measurement;
  continuously calibrate the TRV's internal setpoint offset.
- Window/door sensors switch heating off; restore on close.
- Outdoor temp threshold / weather forecast decides heat on/off seasonally.
- Group multiple TRVs into one logical thermostat.
- Valve maintenance cycles so valves don't stick over summer.
- Control algorithms: TPI, PID (+beta autotune), MPC, "AI Time Based".
- Preset temperatures as editable number entities, persisted.

### Versatile Thermostat (MIT) — most complete framework
Virtual thermostat over three underlying types:
- `over_switch`: direct on/off heater, TPI algorithm:
  `on_percent = coef_int*(target-current) + coef_ext*(target-outdoor)`
  clamped 0..1, plus min activation/deactivation delays and hysteresis
  thresholds. Auto-TPI learns the coefficients.
- `over_climate`: wraps an underlying climate device and self-regulates it
  (offsets its setpoint using room vs TRV internal temp difference).
- `over_valve`: controls valve opening percentage directly.

Central features matching our vision:
- **Central boiler control**: binary_sensor turns boiler on when N devices
  request heat (hvac_action=heating) or total active power exceeds a
  threshold; configurable activation service + delay (valve pre-open time)
  + keep-alive resend. Warns about safety (firing boiler with closed valves).
- Central mode: one place sets mode/setpoints for all VTherms.
- Safety: security mode fallback on sensor failure, heating failure
  detection (heating hard but temp not rising → window open/failure),
  stuck-valve diagnosis, auto start/stop using temperature slope (EMA).

## 3. Gap analysis → what HCC should be

No single project does all of: boiler-level optimization (SAT) + room-level
TRV intelligence (BT/VT) + true gas-minimization focus + MIT license.

HCC positioning: **supervisory gas-optimal heating controller**:
1. Creates its own climate entity/entities (per zone) that RESPECT requests
   coming from other climate entities/TRVs (like SAT Areas).
2. Drives the boiler at the lowest possible flow temperature & modulation
   that satisfies all zones (weather-compensated curve + PID + low-load
   duty cycling instead of on/off cycling).
3. Aggregates room demands: fire the boiler only when needed, pre-open
   valves, stagger starts, condense-friendly return temps.

## 4. Feature shortlist for HCC v1

From SAT: heating curve (weather comp.), flow setpoint control, multi-room
demand aggregation, low-load duty cycling, open-window detection.
From BT: external room sensor usage, TRV calibration offsets, seasonal
on/off by outdoor temp.
From VT: central boiler entity pattern (thresholds, activation delay,
keep-alive), TPI as alternative simple algorithm, safety/security mode,
auto start/stop via slope.

## 5. Open questions (need user hardware info)

1. Boiler interface available? OpenTherm Gateway / EMS bus / plain
   on-off switch / boiler's own climate entity?
2. TRVs present (brand/integration)? Or radiators without valves?
3. Underfloor or radiators?
4. Single zone or multiple rooms with separate sensors?
5. Outdoor temperature source (sensor or weather integration)?
