# Gas metering

HCC estimates gas consumption without a physical gas meter. Three estimation modes are available depending on what data is present.

## Estimation modes

### Modulation (default)

When the OpenTherm boiler reports modulation %:

```
gas = mod% × nameplate_kW × nomod_factor
```

- **mod%** — current burner modulation from OT (MsgID 17)
- **nameplate_kW** — your boiler's rated heat input (set in options)
- **nomod_factor** — multiplier for when mod=0 but flame is on (default 0.7)

Most accurate when your boiler has a good OT modulation readout.

### ΔT estimate

When mod% is 0 but flame is active (boiler is heating but not reporting modulation):

```
gas = P_max × ΔT / 20K / η
```

- **P_max** — nameplate input kW
- **ΔT** — flow temperature minus return temperature (°C)
- **20K** — reference temperature rise for the design point
- **η** — assumed efficiency (typically 0.9 for condensing)

Uses the real temperature rise in the water as a proxy for gas consumption. Works when you have both flow and return sensors.

### Hydronic kW

When both flow and return temps are available:

```
kW = flow_rate × (flow - return) × constant
```

Requires accurate flow data from the boiler.

## Configuration

Go to **Configure → Gas metering**:

| Option | Default | Description |
|---|---|---|
| Gas nameplate input kW | 0 | Your boiler's rated **input** kW (not output) |
| Gas min input kW | 0 | Minimum modulation in kW (improves low-load accuracy) |
| Gas nomod factor | 0.7 | Fallback when mod=0 but flame is on |
| Gas calibration | 1.0 | Multiplier (calibrate against your actual meter) |
| Gas price | 0 | Price per unit for cost display |
| Gas meter name | — | Custom entity name |

### Finding your nameplate kW

- Check the boiler's data plate (sticker on the front or inside the case)
- Look for "Heat input" or "Gas input" in kW — **not** "Heat output" or "Net output"
- Example: Vaillant ecoTEC Plus 832 has input 31.2 kW / output 29.3 kW → use 31.2

### Calibrating

1. Note the current gas reading in HCC
2. Compare against your actual gas meter over a known period
3. Adjust the **calibration** multiplier:
   - If HCC reads high: reduce calibration (e.g. 0.85)
   - If HCC reads low: increase calibration (e.g. 1.15)
4. Recheck after a week

## Display

The **Home** tab shows the current gas estimate (rate and/or cumulative). The **Diagnostics** tab shows:

- Current estimation mode (modulation / ΔT / hydronic)
- ΔT values (flow - return)
- Current modulation %
- Nameplate and calibration values
- Estimated gas flow rate

## Tips

- **Modulation** is most accurate for boilers with good OT reporting
- **ΔT** is better when modulation reads 0 during low-load operation
- Set `nomod_factor` to match your boiler's low-fire behaviour
- A single calibration multiplier covers all estimation modes
