# Logo design brief — Home Climate Control

## What the product is

**Home Climate Control (HCC)** is an open-source **Home Assistant custom
integration** (installed via **HACS**) that controls multi-zone gas heating
through an **OpenTherm** connection. It replaces "dumb" thermostat logic
with weather compensation: it reads the outside temperature, computes the
lowest flow temperature that keeps every room comfortable, and drives the
boiler gently — saving gas while preventing cold rooms.

Companion project: **Home Climate System** — ESP32/ESP8266 firmware + DIY
hardware that speaks OpenTherm directly to the boiler.

Where the logo appears:
- HACS store listing & GitHub social preview (square, small)
- Home Assistant sidebar icon (must read at ~24 px)
- README header on dark GitHub background
- Device web UI footer

## Visual direction (approved by owner)

Reference mood: `docs/branding/candidates/A_ember_hero.png` — **dark navy
night-time scene, one warm glowing flame**. Warmth against cold. Calm,
confident, not playful.

### Core motif options (designer's choice, in priority order)

1. **Flame within a house outline** — minimal gable roofline (single
   chevron) above a smooth teardrop flame. The house is "home", the flame
   is heat.
2. Flame alone, contained in a rounded-square badge tile.
3. House silhouette where the door/window glows like an ember.

### Color palette

| Role | Hex |
|---|---|
| Background / night navy | `#0B1220` → gradient to `#1A2230` |
| Primary accent — flame orange | `#F59E0B` |
| Inner-flame highlight | `#FFC454` |
| Cool contrast (optional secondary mark) | `#38BDF8` |
| Text / strokes on dark | `#FFFFFF`, secondary `#9FB3C8` |

### Typography (if any wordmark)

Geometric sans-serif — Inter / Manrope / Montserrat SemiBold.
Wordmark text exactly: **Home Climate Control**.
Tagline (banner only): *"Save gas, stay comfortable."*

## Required deliverables

| Asset | Spec |
|---|---|
| Master logo | Vector **SVG**, square composition |
| Logo PNG | 1024×1024 and 512×512, transparent background version + dark-tile version |
| Favicon/avatar | 64×64 legibility check (HA sidebar size) |
| Banner (optional add-on) | 1280×640 for GitHub social preview / HACS card |
| Variants | full-color on dark, full-color on light, mono (white), mono (black) |

## Constraints / do-nots

- Must stay legible at 24–32 px (sidebar/favicon) — avoid thin strokes below
  ~6 % of canvas width, avoid fine detail inside the flame
- No photorealism, no clip-art, no more than two accent colors
- Gradients allowed only if they don't band when flattened
- No text inside the square mark itself (wordmark is separate)
- Flat/modern with at most soft glow; no bevels, no 3D, no drop shadows
  heavier than a subtle ambient glow around the flame

## Tone words

warm · reliable · efficient · engineering-grade calm · open-source
