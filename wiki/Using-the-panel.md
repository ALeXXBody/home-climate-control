# Using the panel

The HCC sidebar panel (click the **Home Climate** icon in the HA sidebar) has these tabs:

## Home

Overview: outdoor temperature, boiler flow/return, total demand, boiler status, and a **floor-plan** of your rooms showing each room's temperature and whether it's calling for heat. Tiles show humidity and target temperature.

## Rooms

One card per room. From here you:

- **Set a target temperature** for a room.
- **Change the preset** (Comfort / Eco / Away / Boost / None).
- **Turn a room on/off** (HVAC mode).
- **Edit** a room (TRV, sensor, floor, heat-control mode).

The per-room cards show live demand, whether the radiator is open, and window-open detection.

## Devices

The HCS board(s). Shows the node id, firmware version, online state, and the **Firmware update** action (OTA).

## Settings

Global tuning: curve (min/max flow, coefficient), auto-tune, auto-flow-cap, TRV balancing, boiler min modulation, gas meter settings, presets, wind compensation, schedule and occupancy.

> **Auto-Optimize** lives here — it's the master switch for the gas optimizers.

## Statistics

- Daily **gas** (kWh + cost) and **heat demand** bar charts (last 30 days).
- Gas-vs-outdoor scatter with a trend line.
- A recent-days table.

## Diagnostics

Control-loop internals: curve chart, condensing/flow-cap state, setback learning per room, dead-time estimates, insulation scores, calibration and balancing — useful when tuning or debugging.

## Firmware

List of the HCS firmware releases, with an **Install** button per board (OTA).

## Log

The board's OpenTherm console (frame-level) and syslog, for debugging OpenTherm issues.

---

Next: [Gas optimization](Gas-optimization).
