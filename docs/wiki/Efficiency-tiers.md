# Efficiency tiers

Practical roadmap for heating efficiency features.

| Tier | Needs | HCC status (v1.4.5) |
|---|---|---|
| **0** | Room temp + boiler switch | Calibration °C/h, dead-time + optimal-start, duty cycle, CycleGuard, open-window, health flags, gas estimate |
| **0b** | + outdoor temp | Heating curve, HA outdoor fallback, load-aware health, condensing return pull-down |
| **1** | Internet / HA helpers | Schedule → presets |
| **2** | Phones / contacts | Occupancy (optional), window contacts |
| **3** | Cheap sensors | CO₂ volume, lux solar — not yet |
| **4** | OT / meters / TRV fleet | Partial (return temp, modulation, ΔT kW); full radiator watts / balancing later |

### Optimal-start formula

```
lead = dead_time + deficit / warm_rate + margin
```

Setback depth is sized so recovery + dead-time fit ~1 hour. Reactive pre-heat runs on away/eco when the lead already exceeds that budget.
