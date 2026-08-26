# Options & settings

**Settings → Devices & services → Home Climate Control → Configure**

| Option | Default | Notes |
|---|---|---|
| Min / max flow °C | 25 / 75 | Boiler clamp |
| Curve coefficient | 1.2 | Auto-tune can adjust |
| Auto-tune curve | on | |
| Learn smart setbacks | on | |
| Outdoor temperature fallback | — | `sensor.*` or `weather.*` if boiler outdoor missing/stale (>30 min) |
| Boiler min modulation % | 20 | Below this → duty cycle |
| Low-load duty cycling | on | Long on/off PWM |
| Heating schedule entity | — | `schedule.*`, `input_select`, `sensor` |
| Schedule on / off presets | comfort / eco | For `schedule.*` windows |
| **Occupancy auto-setback** | **off** | Enable after picking trackers |
| Presence entities | — | `device_tracker.*`, `person.*`, presence `binary_sensor` |
| Occupancy away / home presets | away / comfort | Home prefers live schedule if configured |
| Gas nameplate kW, min kW, nomod factor, calibration, price | … | Metering |

## Occupancy behaviour (optional — off by default)

1. Turn **Occupancy auto-setback** **on** in integration **Configure**  
2. Select one or more phone/person trackers  
3. **All away** → away preset on every smart room  
4. **Anyone home** → home preset, or the **schedule** preset if a schedule is set  
5. Manual preset on a room stays sticky until occupancy or schedule changes  
6. Diagnostics tab shows last presence → preset when enabled  

## Schedule behaviour

- `schedule.*`: entity **on** → on-preset; **off** → off-preset  
- Other entities: state should be a preset name (`eco`, `away`, `comfort`, …) or alias (`home`, `night`, …)  
