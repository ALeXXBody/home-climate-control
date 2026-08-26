# Failsafe & CycleGuard

## Failsafe (connection-loss protection)

When the HCS board loses contact with Home Assistant (MQTT down, WiFi lost), failsafe prevents the house from getting cold.

### State machine

| State | Condition | Behaviour |
|---|---|---|
| **Connected** | WiFi up, MQTT connected | Normal — HA commands rule |
| **Hold** | Link lost, inside grace period | Runs last commanded state unchanged |
| **Failsafe** | Link lost beyond grace period | CH forced ON at failsafe flow setpoint; WC bypassed |

### Configuration

| Setting | Default | Range | Where |
|---|---|---|---|
| Enable | on | — | Board web UI / MQTT / HCC panel |
| Flow setpoint | 40 °C | 20–90 °C | Board web UI / MQTT / HCC panel |
| Grace period | 10 min | 1–120 min | Board web UI / MQTT / HCC panel |

### How it works

1. **Normal operation** — HA sends CH enable + flow setpoint every few seconds
2. **Link lost** (WiFi down, MQTT broker unreachable) — enters **Hold** state; keeps the last commanded CH/flow
3. **Grace period expires** — enters **Failsafe** state:
   - CH forced ON
   - Flow setpoint forced to failsafe value (40 °C default)
   - Weather compensation bypassed (predictable flow)
4. **Link restored** — restores pre-failsafe CH/flow state; HA resumes control

### When it triggers

- WiFi disconnect (router reboot, power outage)
- MQTT broker goes down
- HA restart (brief — usually within grace period)
- Network cable pulled from broker

### When it does NOT trigger

- First-install portal mode (no MQTT configured yet)
- Normal HA restarts (usually <10 min)
- Board reboot (starts in CH-off state per `CH_FAILSAFE_OFF_ON_BOOT`)

### Visibility

- Board web UI: **FAILSAFE** badge
- HCC panel: "Heating failsafe" indicator
- MQTT: `hcs/<node>/failsafe` retained → `OFF` / `HOLD` / `ON`
- `/api/status` → `failsafe{}` JSON

---

## CycleGuard

Prevents short-cycling of the boiler burner.

### What it does

- **Minimum-on floor** — once the burner fires, it stays on for a minimum duration
- **Adaptive rest** — after the burner turns off, it waits a calculated rest period before restarting
- Rest period adapts to conditions (longer rest when outdoor is mild, shorter when cold)

### Why it matters

Short-cycling (frequent on/off) wastes gas and wears the boiler. A single 30-minute burn at low modulation is more efficient than ten 3-minute burns.

### How it works

CycleGuard monitors the burner state from OT modulation data:

1. **Burner ON** → start minimum-on timer
2. **Burner OFF** → calculate rest period based on outdoor temp and recent cycle history
3. During rest, suppress new CH enable requests (even if rooms are calling)
4. Rest ends → allow next cycle

### Interaction with duty cycling

- CycleGuard and duty cycling work together
- Duty cycling handles "demand too low for boiler minimum" — long on/off periods
- CycleGuard handles "boiler just turned off" — prevents immediate restart
- Both are most active during mild weather (low load)

### Tuning

CycleGuard is automatic — no user configuration needed. It adapts based on:
- Outdoor temperature (colder = shorter rest)
- Recent cycle history (learns typical patterns)
- Boiler modulation range (wider range = more flexibility)
