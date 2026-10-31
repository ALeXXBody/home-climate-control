# Audit — zone-config field pipeline (2026-10-31)
Scope: every field in the Rooms add/edit forms; the full path panel → wire
schema → handler → build/patch → stored options → runtime zone.
Method: static trace matrix across the layers, then HANDLER-LEVEL tests
(tests/test_zone_edit_audit.py runs the real ws_rename_zone / ws_add_zone
coroutines and asserts the SAVED OPTIONS — the seam the earlier fixes
whe daylight out of).

## The trace matrix (v1.24.1 پیدا at audit time)

| Field | schema(add) | handler(add) | schema(rename) | handler(rename) | build | panel(add) | panel(edit) |
|---|---|---|---|---|---|---|---|
| trv_climates | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| temp_sensor | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| humidity_sensor | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| window_sensors | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| lux_sensor | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| co2_sensor | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| trv_position_entity | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| radiator_kw (stored) | ✓ | ✓ | ✓ | ✓ | ✓ | n/a (panel speaks W) | n/a |
| **radiator_w (UI)** | ✓ | ✓* | ✓ | ✓* | ✓ | ✓ | ✓ |
| floor_loop/mixer/surface/flow/pump | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| floor_surface_max | ✓ | ✓ | ✓ | ✓ | ✓ | — (add form has no input; default 29 used) | ✓ |

* = was a found hole, fixed in this audit.

## Found holes (all fixed, each proven by a handler-level test)
1. **H1** (fixed v1.24.0→): non-floor edits carried the five floor keys as
   nulls → wire rejection ("not a valid option at floor_*").
2. **H2** (fixed 1.24.1→): the rename_zone WIRE SCHEMA never had the six
   floor keys at all — they existed only on add_zone; floor-room edits were
   structurally rejected.
3. **H3** (this audit): both handlers read/validate nothing for radiatore
   watts: v1.24.0's W field was accepted at the wire, converted by the
   builder, and dropped between — silent no-save.
4. **H4** (this audit): the rename edit-gate returned "Nothing to change"
   when the watts were the ONLY field changed — the watts field was not
   counted as a change.
5. **H5** (this audit): add_zone's builder call did not pass radiator_w
   through (covered by the same v1.24.0 wiring skip).

Remaining intentional design (not holes, recorded):
- add form has no floor_surface_max input (radiator-era decision); default
  applies; the edit form exposes it for floor rooms.
- TRV big-temp fields use their own decimal handling (.5 grid from the TRV
  integrations) — not part of this audit's surface.

## Test coverage added (the seam tests)
tests/test_zone_edit_audit.py — runs the REAL handler coroutines and asserts
saved OPTIONS: set / clear-null / absent-never-wipes / out-of-band rejects
per field. If a future field forgets its pass-through, these tests fail at
commit time — before a user's save silently vanishes again.
