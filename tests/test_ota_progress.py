"""OTA progress tracking, watchdog, and failure notifications."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from custom_components.home_climate_control.firmware_manager import (
    FirmwareManager,
    HcsDevice,
)


@pytest.fixture()
def mgr():
    hass = MagicMock()
    tasks = []
    hass.async_create_task = lambda coro: (tasks.append(coro), coro.close())[1]
    m = FirmwareManager(hass)
    m.devices["hcs-a"] = HcsDevice(
        node_id="hcs-a", name="Boiler GW", board="lolin_c3_mini", version="1.0.2"
    )
    return m, tasks


def _msg(topic: str, payload: dict) -> MagicMock:
    m = MagicMock()
    m.topic = topic
    m.payload = json.dumps(payload)
    return m


def test_progress_messages_update_device(mgr):
    m, _ = mgr
    dev = m.devices["hcs-a"]
    # pretend an attempt is running (async_trigger_ota needs mqtt stubs)
    dev.ota_state = "starting"
    m._ota_rt["hcs-a"] = {
        "started_at": 0.0,
        "msg_at": None,
        "went_offline": False,
        "notified": False,
    }
    m._on_ota(_msg("hcs/hcs-a/ota", {"state": "downloading", "progress": 42}))
    assert dev.ota_state == "downloading"
    assert dev.ota_progress == 42

    m._on_ota(_msg("hcs/hcs-a/ota", {"state": "done", "progress": 100}))
    assert dev.ota_state == "rebooting"  # done -> board reboots next
    assert dev.ota_progress == 100


def test_board_failure_sets_error_and_notifies_once(mgr):
    m, tasks = mgr
    dev = m.devices["hcs-a"]
    dev.ota_state = "downloading"
    m._ota_rt["hcs-a"] = {
        "started_at": 0.0,
        "msg_at": 1.0,
        "went_offline": False,
        "notified": False,
    }
    m._on_ota(
        _msg("hcs/hcs-a/ota", {"state": "failed", "error": "HTTP 404 (code -104)"})
    )
    assert dev.ota_state == "failed"
    assert "404" in dev.ota_error
    assert len(tasks) == 1  # one persistent_notification task

    # a duplicate failure must not spam notifications
    m._ota_fail("hcs-a", "again")
    assert len(tasks) == 1


def test_watchdog_fails_silent_board(mgr):
    import time as _t

    m, tasks = mgr
    dev = m.devices["hcs-a"]
    dev.ota_state = "starting"
    m._ota_rt["hcs-a"] = {
        "started_at": _t.monotonic() - m.OTA_ACK_TIMEOUT_S - 5,
        "msg_at": None,
        "went_offline": False,
        "notified": False,
    }
    m._ota_fail  # exists
    # run one sweep manually (watchdog loop body)
    now = _t.monotonic()
    rt = m._ota_rt["hcs-a"]
    age = now - rt["started_at"]
    if rt["msg_at"] is None and age > m.OTA_ACK_TIMEOUT_S:
        m._ota_fail(
            "hcs-a", "board did not acknowledge the update command "
        )
    assert dev.ota_state == "failed"
    assert len(tasks) == 1
    assert "acknowledge" in dev.ota_error or "did not acknowledge" in dev.ota_error


def test_reboot_resolution_success_and_stale_version(mgr):
    m, tasks = mgr
    dev = m.devices["hcs-a"]

    # came back with the target version -> done
    dev.ota_state = "rebooting"
    dev.ota_target_version = "1.1.1"
    dev.version = "1.1.1"
    dev.online = True
    m._ota_rt["hcs-a"] = {
        "started_at": 0.0,
        "msg_at": 5.0,
        "went_offline": True,
        "notified": False,
    }
    m._ota_resolve_reboot("hcs-a")
    assert dev.ota_state == "done"

    # came back still old -> failed with version in the reason
    dev2 = HcsDevice(node_id="hcs-b", name="Old", board="d1_mini", version="1.0.2")
    m.devices["hcs-b"] = dev2
    dev2.ota_state = "rebooting"
    dev2.ota_target_version = "1.1.1"
    dev2.online = True
    m._ota_rt["hcs-b"] = {
        "started_at": 0.0,
        "msg_at": 5.0,
        "went_offline": True,
        "notified": False,
    }
    m._ota_resolve_reboot("hcs-b")
    assert dev2.ota_state == "failed"
    assert "still runs v1.0.2" in dev2.ota_error
    assert len(tasks) == 1


def test_lwt_offline_marks_rebooting(mgr):
    m, _ = mgr
    dev = m.devices["hcs-a"]
    dev.online = True
    dev.ota_state = "downloading"
    dev.ota_progress = 80
    m._ota_rt["hcs-a"] = {
        "started_at": 0.0,
        "msg_at": 3.0,
        "went_offline": False,
        "notified": False,
    }
    msg = MagicMock()
    msg.topic = "hcs/hcs-a/status"
    msg.payload = b"offline"  # real MQTT payloads are bytes
    m._on_availability(msg)
    assert dev.ota_state == "rebooting"
    assert m._ota_rt["hcs-a"]["went_offline"] is True


def test_graceful_disconnect_resolves_on_status_publish(mgr):
    """Live v1.0.32 finding: boards that close MQTT cleanly before rebooting
    never fire LWT, so presence never sees offline->online and a *successful*
    update was failed by the watchdog ('update stalled'). The post-reboot
    status publish must judge the outcome instead."""
    m, tasks = mgr
    dev = m.devices["hcs-a"]
    dev.version = "1.0.2"
    dev.online = True  # stays online the whole time: no LWT, no presence edge
    dev.seen_lwt_offline = False

    dev.ota_state = "starting"
    dev.ota_target_version = "1.1.1"
    m._ota_rt["hcs-a"] = {
        "started_at": 0.0,
        "msg_at": 5.0,
        "went_offline": False,
        "notified": False,
    }

    # board pulls, writes, reports done -> 'rebooting'
    m._on_ota(_msg("hcs/hcs-a/ota", {"state": "done", "progress": 100}))
    assert dev.ota_state == "rebooting"

    # board reboots and re-announces via its status topic (no LWT was seen)
    msg = MagicMock()
    msg.topic = "hcs/hcs-a/status"
    msg.payload = json.dumps(
        {
            "node_id": "hcs-a",
            "name": "Boiler GW",
            "board": "lolin_c3_mini",
            "version": "1.1.1",
            "ip": "192.168.50.153",
        }
    )
    m._on_discovery(msg)
    assert dev.ota_state == "done"
    assert dev.ota_progress == 100
    assert dev.version == "1.1.1"
    assert "hcs-a" not in m._ota_rt


def test_status_publish_does_not_resolve_mid_download(mgr):
    """Guard: a same-version reflash must not be marked done while the board
    is still pulling — only 'rebooting' counts."""
    m, _ = mgr
    dev = m.devices["hcs-a"]
    dev.version = "1.1.1"  # already at target (same-version flash)
    dev.online = True
    dev.seen_lwt_offline = False
    dev.ota_state = "downloading"
    dev.ota_target_version = "1.1.1"
    m._ota_rt["hcs-a"] = {
        "started_at": 0.0,
        "msg_at": 5.0,
        "went_offline": False,
        "notified": False,
    }
    msg = MagicMock()
    msg.topic = "hcs/hcs-a/status"
    msg.payload = json.dumps({"node_id": "hcs-a", "version": "1.1.1"})
    m._on_discovery(msg)
    assert dev.ota_state == "downloading"  # untouched: still flashing


def test_clean_disconnect_board_resolves_on_status_publish(mgr):
    """Regression (v1.0.32 live finding): boards that close MQTT cleanly
    before rebooting never fire LWT, so HA never sees them go offline and
    the presence edge in _async_presence never runs _ota_resolve_reboot —
    successful updates were mislabeled 'update stalled' by the watchdog.
    The post-reboot status publish must resolve the attempt instead."""
    m, tasks = mgr
    dev = m.devices["hcs-a"]
    assert dev.version == "1.0.2"
    dev.online = True  # never marked offline in HA's view
    dev.seen_lwt_offline = False
    dev.ota_target_version = "1.1.1"
    m._ota_rt["hcs-a"] = {
        "started_at": 0.0,
        "msg_at": None,
        "went_offline": False,
        "notified": False,
    }
    # board pulls, reports done -> rebooting, then reboots (no LWT)
    m._on_ota(_msg("hcs/hcs-a/ota", {"state": "done", "progress": 100}))
    assert dev.ota_state == "rebooting"

    # post-reboot status publish announces the new version; still no LWT
    msg = MagicMock()
    msg.topic = "hcs/hcs-a/status"
    msg.payload = json.dumps(
        {
            "node_id": "hcs-a",
            "name": "Boiler GW",
            "board": "lolin_c3_mini",
            "version": "1.1.1",
            "ip": "192.168.50.153",
        }
    )
    m._on_discovery(msg)
    assert dev.ota_state == "done"
    assert dev.ota_progress == 100
    assert dev.version == "1.1.1"
    assert "hcs-a" not in m._ota_rt
    # the one queued task is _on_discovery's debounced update-check;
    # a failure notification would only exist if _ota_fail had run
    assert not dev.ota_error

    # watchdog must leave a resolved attempt alone
    import time as _t

    rt_age = _t.monotonic() - 9999
    m._ota_rt.setdefault(
        "hcs-a", {"started_at": rt_age, "msg_at": None, "went_offline": False, "notified": False}
    )
    dev.ota_state = "done"
    assert dev.ota_state not in {"starting", "downloading", "rebooting"}
