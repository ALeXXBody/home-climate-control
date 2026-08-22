# Home Climate Control — Architecture v1

Status: draft. Target platform: Home Assistant custom component (HACS).
License plan: private during development, MIT on first release.

**Repos**

| Product | Repo | Role |
|---|---|---|
| Home Climate Control | `ALeXXBody/home-climate-control` | HA software (this doc) |
| Home Climate System | `ALeXXBody/home-climate-system` | ESP32/ESP8266 firmware + hardware |

Do not confuse with third-party **SAT** (Alexwijn/SAT) — research reference only.

## Design goals

1. Create HA climate entities (one per zone) that users interact with.
2. Respect requests from other climate entities (smart TRVs in rooms).
3. Minimize gas consumption while honoring those requests.
4. Radiators first; underfloor-ready (per-zone emitter config).
5. Clean-room code (only MIT sources may be reused).

## Gas-minimization strategy (the "why" of every module)

Ordered by impact:
1. **Weather-compensated low flow temperature** — run the boiler at the
   lowest flow setpoint that satisfies the coldest-demanding zone.
   Lower return temps → condensing mode → 10-20% gas savings.
2. **Modulation over on/off** — keep burner lit at low power instead of
   short-cycling at min-modulation.
3. **Low-load duty cycling** — when computed demand < boiler minimum
   modulation, cycle on/off with calculated duty instead of letting the
   boiler overshoot and short-cycle.
4. **Overshoot avoidance** — stop heating early using room heat inertia
   (slope-based prediction), don't waste heat past setpoint.
5. **Demand suppression** — window open → pause zone; outdoor temp above
   threshold → season off; all zones satisfied → boiler off.

## Component structure

```
custom_components/home_climate_control/
├── __init__.py            # setup entry, stores shared CentralController
├── config_flow.py         # UI setup: boiler backend, zones
├── manifest.json
├── const.py
├── central.py             # CentralController: demand aggregation + flow setpoint
├── boiler/
│   ├── __init__.py        # BoilerBackend ABC: set_flow_temp, get_modulation,
│   │                      #   get_return_temp, get_flame, enable_ch...
│   ├── otgw_mqtt.py       # OpenTherm Gateway via MQTT (otgw-firmware topics)
│   ├── esphome_ot.py      # ESPHome opentherm entities backend
│   └── switch.py          # (phase 2) plain relay fallback
├── heating_curve.py       # flow = f(outdoor, room_setpoint); radiator/UF variants
├── pid.py                 # PID w/ anti-windup + auto-gains from curve coefficient
├── zone.py                # ZoneClimateEntity (ClimateEntity)
├── demand.py              # DemandSource protocol (own zone | external climate entity)
├── sensors.py             # binary_sensor: window groups, boiler state diagnostics
└── number.py              # tunables exposed to UI (curve coeff, OPV, thresholds)
```

## Key mechanisms

### Zones (climate entities HCC creates)
Each zone = one room group:
- `temperature_sensor`: authoritative room temp (external sensor preferred).
- Optional `trv_climate` list (mixed homes):
  - HCC reads their `hvac_action` as demand evidence;
  - HCC pushes calibrated setpoints back (offset = trv_internal − room_temp),
    like VT self-regulation, so TRVs don't fight the system.
- Zone output = **demand level** 0..1 from PID(error) where error uses the
  *maximum* deficit across the zone's rooms (Comfort-style aggregation).

### CentralController (the gas optimizer)
Runs every control tick (default 60 s):
1. Collect zone demands + each zone's required flow temp from heating curve:
   `flow_zone = clamp(curve(outdoor, setpoint_zone) + k·error_zone, min, max_flow)`
2. Boiler flow setpoint = `max(flow_zone)` over zones with demand > 0.
3. If no demand → CH off. If total demand < boiler min modulation →
   duty-cycle mode (on/off timing from measured rise/fall rates).
4. Publishes: `sensor.hcc_flow_setpoint`, `sensor.hcc_total_demand`,
   `binary_sensor.hcc_boiler_on`, diagnostic attributes (return temp,
   modulation, estimated instant gas use from min/max consumption).

### Outdoor temperature source (priority order)
1. Boiler's own outdoor sensor reported by OTGW via MQTT (`Tout` /
   `outdoor_sensor_value`) — primary, no extra hardware needed.
2. Fallback: any HA temperature sensor / weather integration entity,
   selectable in options if MQTT value is missing or stale (>30 min).

### Heating curve
Radiator variant first: Precision-curve family
`flow = setpoint + curve_coeff · (setpoint_winter − outdoor)/(setpoint_winter − outdoor_design)`
clamped [min_flow .. max_flow]; coefficients user-tunable via number entities.
Underfloor variant = same formula, lower clamps + longer sample time.

## Phased roadmap

**Phase 1 — MVP (radiators, OTGW MQTT):**
- config flow: gateway topic/prefix, outdoor temp source, max flow temp,
  zones (room sensor [+ optional TRV climates])
- heating curve + central flow setpoint control
- zone climate entities with presets (none/away/eco/comfort/boost)
- window detection pauses zone
- diagnostics entities + basic gas estimate

**Phase 2 — optimization:**
- auto-gains PID tuning wizard (SAT-style calibration run)
- low-load duty cycling, slope-based overshoot cutoff (auto start/stop)
- TRV calibration offsets learned over time

**Phase 3 — breadth:**
- switch/relay boiler backend, ESPHome OT backend polish
- underfloor profiles, DHW control, seasonal on/off
- energy dashboard integration (gas kWh), long-term stats

## Explicitly out of scope (v1)
Cooling, heat pumps, AC, presence/motion detection, power shedding.
