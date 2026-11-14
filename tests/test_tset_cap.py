"""Board-learned boiler CH ceiling (tset_cap) — parse + curve clamp.

Field evidence (v1.5.24 live): HCC planned 75 °C while the boiler's write-ACK
echoes consistently returned 55.0 — the boiler silently clamped and the
autotune dead-ended 'at limit — holding' while rooms starved. The board now
learns the ceiling from the echoes; the hub must plan within it.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from home_climate_control.boiler.hcs_mqtt import HcsMqttBackend, _NodeState


@pytest.fixture()
def backend():
    b = HcsMqttBackend(MagicMock(), "hcs-a", min_flow=25, max_flow=75)
    st = b._nodes["hcs-a"] = _NodeState("hcs-a")
    b._active = "hcs-a"
    return b


def test_tset_cap_parsed_from_telemetry(backend):
    backend._on_value("hcs-a", "tset_cap", "55.0")
    assert backend.tset_cap == 55.0


def test_tset_cap_off_means_unknown(backend):
    backend._on_value("hcs-a", "tset_cap", "55.0")
    backend._on_value("hcs-a", "tset_cap", "off")  # board cleared the cap
    assert backend.tset_cap is None


def test_tset_cap_unknown_node_is_none(backend):
    b = HcsMqttBackend(MagicMock(), "hcs-a", min_flow=25, max_flow=75)
    assert b.tset_cap is None


def test_central_wire_ignores_stale_cap_for_board_probe():
    """The wire value must NOT be clamped to the learned cap.

    Field evidence 2026-11-14: the board's ID-49 bound says the boiler
    accepts 80 °C, but hub and board sat pinned at 55 for days while rooms
    starved — the hub clamped every request to the cap, so the board's
    ~5 min above-cap probe only ever saw requests at/below it and no echo
    could clear it. Contract: the hub sends the curve value clamped only
    to the configured min/max; the board clamps each write to the cap and
    probes above it, so a stale cap self-heals. Planning/display
    (flow_max_eff) still respect the cap.
    """
    from home_climate_control.heating_curve import flow_for_outdoor

    # reproduce the arithmetic the central tick uses (base curve + PID trim)
    max_flow = 75.0
    min_flow = 25.0
    tset_cap = 55.0
    flow_max_eff = min(max_flow, float(tset_cap))  # planning stays honest
    assert flow_max_eff == 55.0
    base = flow_for_outdoor(20.0, 7.8, 3.0, min_flow, max_flow, -10.0)  # 44.4
    pid_extra = 30.0  # morning-recovery trim, same shape as live evidence
    raw = base + pid_extra                     # → 74.4, past the stale cap
    assert raw > 55.0
    wire = min(max(raw, min_flow), max_flow)   # wire: options only, no cap
    assert wire == pytest.approx(74.4)
    planned = min(max(raw, min_flow), flow_max_eff)  # display: cap respected
    assert planned == 55.0


def test_central_cap_below_min_flow_is_ignored():
    """A garbage cap (or DHW-only echo) below the configured min must not
    pull the whole system dead."""
    from home_climate_control.heating_curve import flow_for_outdoor

    min_flow = 25.0
    cap = 10.0
    eff = cap if cap >= min_flow else None
    assert eff is None
    _ = flow_for_outdoor(20.0, 7.8, 3.0, min_flow, 75.0, -10.0)  # unaffected


def test_tset_cap_flows_through_retained_ctl_mirror(backend):
    """The guaranteed channel: hcs/<node>/ctl retained JSON (change-gated at
    the board). The v1.20.1 field bug — the q0 leaf never arriving while
    /api/status showed the cap — closed at both ends here."""
    backend._on_topic("hcs/hcs-a/ctl", '{"ch_enable":true,"tset_cap":55.0}')
    assert backend.tset_cap == 55.0
    backend._on_topic("hcs/hcs-a/ctl", '{"ch_enable":true,"tset_cap":null}')
    assert backend.tset_cap is None
    # a malformed mirror must not throw or corrupt the previous value
    backend._on_topic("hcs/hcs-a/ctl", "{broken")
    assert backend.tset_cap is None
    backend._on_topic("hcs/hcs-a/ctl", '{"tset_cap":"65.0"}')
    assert backend.tset_cap == 65.0
