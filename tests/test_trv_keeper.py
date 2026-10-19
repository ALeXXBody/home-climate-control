"""TRV external-temperature keeper (Sonoff TRVZB / Zigbee2MQTT field case).

Upstream zigbee2mqtt#29650: the TRVZB flaps its temperature_sensor_select on
its own; never fixed (closed not_planned). Firmware 1.4.x additionally falls
back to the internal sensor when the external feed stalls. HCC owns the
feed, the select guardian and the drift watch.
"""

import asyncio
import time

from unittest.mock import AsyncMock, MagicMock

import pytest

from homeassistant.components.climate import HVACMode
from custom_components.home_climate_control.zone import ZoneClimateEntity

NOW = time.monotonic()
INPUT = "number.office_trv_external_temperature_input"
SELECT = "select.office_trv_temperature_sensor_select"
CLIMATE = "climate.office_trv"


def _zone(cur=18.4, ext=18.2, select_state="remote_temperature",
          trv_cur=18.4, heat_control="smart"):
    z = object.__new__(ZoneClimateEntity)
    z.heater_control = heat_control
    z._trv_entity = CLIMATE
    z._trv_climates = [CLIMATE]
    z._trv_position_entity = "number.office_trv_valve_opening_degree"
    z._hvac_mode = HVACMode.HEAT
    z._window_open = False
    z._current_temp = cur
    z._last_temp_update = None
    z.demand_level = lambda: 0.5
    z._zone_name = lambda: "Office"
    z.effective_setpoint = lambda: 21.0
    states = {
        INPUT: MagicMock(state=str(ext) if ext is not None else "unknown"),
        SELECT: MagicMock(state=select_state),
        CLIMATE: (MagicMock(attributes={"hvac_action": "heating",
                                        "current_temperature": trv_cur})
                  if trv_cur is not None else None),
    }
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.states.get = states.get
    z.hass = hass
    z._hass = hass
    z.coordinator = MagicMock()
    z.coordinator.debug_log = MagicMock()
    z._trv_keep_feed_at = 0.0
    z._trv_keep_feed_val = None
    z._trv_keep_select_at = 0.0
    z._trv_keep_select_notified = False
    z._trv_drift_since = None
    z._trv_drift = False
    z._trv_drift_notified = False
    z._trv_keep_feed_entity = None
    z._trv_keep_select_entity = None
    return z, hass, states


def _calls(hass, domain):
    return [c for c in hass.services.async_call.call_args_list
            if c[0][0] == domain]


def test_item_entities_derived_from_slug():
    z, hass, _ = _zone()
    asyncio.run(z.trv_keeper_tick(NOW, hass))
    assert z._trv_keep_feed_entity == INPUT
    assert z._trv_keep_select_entity == SELECT


def test_feed_writes_room_temp():
    z, hass, _ = _zone(cur=18.4, ext=18.2)
    asyncio.run(z.trv_keeper_tick(NOW, hass))
    calls = _calls(hass, "number")
    assert len(calls) == 1
    assert calls[0][0][2]["value"] == 18.4
    assert z._trv_keep_feed_at == NOW


def test_feed_skips_when_close_and_recent():
    z, hass, _ = _zone(cur=18.4, ext=18.4)
    z._trv_keep_feed_entity = INPUT
    z._trv_keep_select_entity = SELECT
    z._trv_keep_feed_at = NOW            # just fed
    asyncio.run(z.trv_keeper_tick(NOW, hass))
    assert _calls(hass, "number") == []


def test_keepalive_rewrite_even_when_stable():
    """A stable room must still be re-written ≤ every 5 min — a silent feed
    is exactly what triggers the TRVZB's internal-sensor fallback (the daily
    Δ=5.5 K alarm class)."""
    z, hass, _ = _zone(cur=18.4, ext=18.4)   # no movement at all
    z._trv_keep_feed_entity = INPUT
    z._trv_keep_select_entity = SELECT
    z._trv_keep_feed_at = NOW - 301.0        # feed silent for 5 min
    asyncio.run(z.trv_keeper_tick(NOW, hass))
    calls = _calls(hass, "number")
    assert len(calls) == 1
    assert calls[0][0][2]["value"] == 18.4


def test_feed_skips_when_room_unmeasured():
    z, hass, _ = _zone(cur=None, ext=18.2)
    asyncio.run(z.trv_keeper_tick(NOW, hass))
    assert _calls(hass, "number") == []


def test_stale_room_temp_is_never_fed():
    """The staleness guard must apply: a sensor that stopped updating must
    not freeze its room by feeding stale values."""
    z, hass, _ = _zone(cur=18.4, ext=18.2)
    import custom_components.home_climate_control.zone as zone_mod
    orig = z._temp_current
    z._temp_current = lambda: orig()   # 90-min staleness guard fallback:...
    z._current_temp = 18.4
    z._last_temp_update = None
    # _temp_current with no _last_temp_update returns cur → simulate stale
    z._last_temp_update = NOW - 91 * 60
    asyncio.run(z.trv_keeper_tick(NOW, hass))
    assert _calls(hass, "number") == []


def test_guardian_re_asserts_unknown_select():
    z, hass, _ = _zone(select_state="unknown")
    asyncio.run(z.trv_keeper_tick(NOW, hass))
    calls = _calls(hass, "select")
    assert len(calls) == 1
    assert calls[0][0][2]["option"] == "remote_temperature"
    # one notification per episode
    notifs = _calls(hass, "persistent_notification")
    assert len(notifs) == 1


def test_guardian_skips_valid_and_unavailable():
    for st in ("remote_temperature", "local_temperature",
               "remote_source_offline", "unavailable"):
        z, hass, _ = _zone(select_state=st)
        asyncio.run(z.trv_keeper_tick(NOW, hass))
        assert _calls(hass, "select") == [], st


def test_guardian_respects_cadence_and_nonotifies_when_healthy():
    z, hass, _ = _zone(select_state="unknown")
    z._trv_keep_select_entity = SELECT
    asyncio.run(z.trv_keeper_tick(NOW, hass))      # re-assert + notify
    NEXT = NOW + 300.0                             # inside the 10-min window
    states2 = {"select.office_trv_temperature_sensor_select":
               MagicMock(state="unknown")}
    z.hass.states.get = states2.get
    asyncio.run(z.trv_keeper_tick(NEXT, z.hass))   # cadence still hot
    assert len(_calls(z.hass, "select")) == 1


def test_guardian_notifies_once_per_episode():
    z, hass, _ = _zone(select_state="unknown")
    z._trv_keep_select_entity = SELECT
    asyncio.run(z.trv_keeper_tick(NOW, hass))
    z._trv_keep_select_at = 0.0
    asyncio.run(z.trv_keeper_tick(NOW + 700.0, hass))   # drifted again → re-assert
    assert len(_calls(hass, "select")) == 2
    assert len(_calls(hass, "persistent_notification")) == 1  # notified once


def test_drift_flags_after_15_min_of_divergence():
    z, hass, _ = _zone(cur=18.4, trv_cur=16.0)   # 2.4 K apart
    asyncio.run(z.trv_keeper_tick(NOW, hass))
    assert z._trv_drift is False
    LATER = NOW + 901.0
    asyncio.run(z.trv_keeper_tick(LATER, hass))
    assert z._trv_drift is True


def test_drift_clears_when_trv_tracks_room():
    z, hass, _ = _zone(cur=18.4, trv_cur=16.0)
    LATER = NOW + 901.0
    asyncio.run(z.trv_keeper_tick(NOW, hass))
    asyncio.run(z.trv_keeper_tick(LATER, hass))
    assert z._trv_drift is True
    states3 = {"select.office_trv_temperature_sensor_select":
               MagicMock(state="remote_temperature")}
    z.hass.states.get = lambda eid: (
        {"number.office_trv_external_temperature_input": MagicMock(state="18.4"),
         "climate.office_trv": MagicMock(
             attributes={"current_temperature": 18.3})}.get(eid))
    asyncio.run(z.trv_keeper_tick(NOW + 1000.0, z.hass))
    assert z._trv_drift is False


def test_valve_and_floor_rooms_are_never_kept():
    for control in ("valve", "manual", "floor"):
        z, hass, _ = _zone(heat_control=control)
        asyncio.run(z.trv_keeper_tick(NOW, hass))
        assert _calls(hass, "number") == []
        assert _calls(hass, "select") == []


def test_valve_failover_and_keeper_can_coexist():
    """The scene from the field: a stuck select (guardian fires) while HCC
    also drives the valve (failover) — no crash, no fight, both write."""
    z, hass, _ = _zone(select_state="unknown", cur=18.4, ext=18.2)
    z._valve_failover = True
    z._valve_failover_cmd = None
    z._valve_failover_cmd_at = 0.0
    z._valve_failover_idle_since = None
    z._valve_stuck_since = None
    z._valve_failover_rearm_until = 0.0
    z._valve_last_write = 0.0
    z._valve_exercising = False
    z.valve_current_pct = lambda hass: 0.0
    asyncio.run(z.trv_keeper_tick(NOW, hass))
    z.valve_apply(NOW, hass)
    assert len(_calls(hass, "select")) == 1
    assert len(_calls(hass, "number")) >= 1
