# Gas optimization — how (and why) this burns less gas

A plain weather-compensation controller picks a flow temperature from the outdoor temperature and leaves it there. HCC adds several layers that *only* exist to spend less gas:

## Condensing (the biggest lever)

A condensing boiler only reaches its ~90%+ efficiency when the **return** water is below the dew point (≈54 °C). Above that it behaves like a non-condensing boiler (~80%). HCC watches the return temperature and, when it climbs above 54 °C, **drops the flow setpoint** to pull the return back into condensing range. This is a constant, automatic efficiency reclaim that a fixed curve never does.

> Requires the board to publish a return temperature. If yours doesn't, HCC warns once in the logs.

## Auto-flow-cap

If the return keeps running hot (oversized radiators, mild weather), HCC trims the **maximum flow** downward so the system stops pushing more heat than the return can reject. Bounded, slow, and only while the system is healthy.

## Duty-cycling at low load

When demand is below the boiler's minimum modulation, a naive controller either short-cycles (on/off every minute — inefficient and wearing) or runs continuously at min fire (overheating). HCC PWMs the burner in long on/off slices so the flame only ever runs at its efficient minimum.

## Cycle-guard

Minimum burn (4 min) + adaptive rest between starts. Fewer, longer burns = more efficient and less wear than many short ones.

## Smart setbacks + optimal start

- **Setbacks** are sized to each room's *actual* recovery speed, so you can drop temperatures further in fast rooms without paying a catch-up burn in the morning.
- **Optimal start** begins warming rooms early enough that they hit your comfort time without a full-power "catch-up" blast.

## Curve auto-tune

The weather-compensation curve slowly converges to your house: rooms chronically cold → steepen, rooms overshooting → flatten. This keeps the flow as low as possible while meeting demand — the definition of using less gas.

## See it working

The **Statistics** tab plots daily gas and heat demand, and the gas-vs-outdoor scatter shows your heating "signature". After a few days you can watch the trend slope down as the optimizers settle in.

---

Next: [Troubleshooting](Troubleshooting).
