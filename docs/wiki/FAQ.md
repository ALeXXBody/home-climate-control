# FAQ

### Board shows old firmware after HCC update

HCC (integration) and HCS (ESP firmware) version separately. Update the board via the **Devices** tab OTA, or download from [HCS releases](https://github.com/ALeXXBody/home-climate-system/releases).

### Board pings but HTTP times out

Power-cycle the ESP. Firmware ≥ 1.4.0 includes fixes for the HTTP layer getting stuck. The board auto-reboots after 2 consecutive self-probe failures.

### Outdoor temperature is blank

Check that the HCS board has an outdoor temperature source:
- **Boiler OT sensor:** verify in the board's web UI (System tab → outdoor temp)
- **HA fallback sensor:** set **Outdoor temperature fallback** in integration Configure
- Without outdoor temp, the heating curve can't calculate a flow target

### Rooms not pre-heating

Pre-heat requires:
1. **Measured warm rate** — from calibration or several setback→comfort transitions
2. **Dead time** — how long until temp starts rising after heat is enabled
3. **An active schedule or occupancy** — pre-heat needs a target time to work towards

Use **Calibrate** on the room card for the fastest path to working pre-heat.

### Occupancy does nothing

- Turn **Occupancy auto-setback** **on** in integration Configure
- Select at least one tracker entity
- Default is off — enabling without trackers does nothing
- Need at least 2 trackers for reliable "all away" detection

### Gas estimate looks wrong

1. Set **nameplate input kW** (not output) in Configure
2. Check the estimation mode in Diagnostics (modulation / ΔT / hydronic)
3. Calibrate against your actual gas meter over 1–2 weeks
4. Adjust the **calibration** multiplier accordingly

### Rooms overshoot target temperature

- The heating curve may be too aggressive — auto-tune should fix this over time
- Check if CycleGuard rest is too short (normal after fresh install)
- Manual flow setpoint override can help while auto-tune learns

### Panel looks broken after update

**Hard-refresh** the browser: Ctrl+Shift+R (or Cmd+Shift+R on Mac). The panel JS is cached by the browser.

### Multiple boards

HCC supports multiple HCS boards on the same MQTT. In the **Devices** tab, select which board to control. Each board is independent — one board per boiler.

### How do presets work?

Presets are named setback profiles:
- **Comfort** — normal heating (target temp from the thermostat)
- **Eco** — slight setback (1–3 °C below comfort)
- **Night** — moderate setback (2–5 °C below comfort)
- **Away** — deep setback (3–8 °C below comfort)

Smart setback learns the depth per room. Auto-tune learns the curve coefficient. Both improve over time.

### Can I use this with non-OpenTherm boilers?

HCS speaks OpenTherm to the boiler. If your boiler doesn't support OT, you'd need an on/off relay interface instead — that's outside HCS's scope.

### Does HCC work without an HCS board?

Yes — **Demo mode** creates simulated boiler and rooms. You can explore the full UI without hardware. For real heating, you need the HCS board.

### Where do I get help?

- [GitHub Issues](https://github.com/ALeXXBody/home-climate-control/issues) — bugs, feature requests
- [HCS Issues](https://github.com/ALeXXBody/home-climate-system/issues) — firmware, hardware
