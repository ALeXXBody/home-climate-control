"""OTA URLs handed to boards must be LAN-reachable (IP, not mDNS names)."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from custom_components.home_climate_control.firmware_manager import FirmwareManager


@pytest.fixture()
def mgr():
    hass = MagicMock()
    hass.async_create_task = lambda coro: coro.close()

    def _run_job(fn, *args):
        fut = asyncio.get_event_loop().create_future()
        try:
            fut.set_result(fn(*args))
        except Exception as exc:  # noqa: BLE001
            fut.set_exception(exc)
        return fut

    hass.async_add_executor_job = _run_job
    return FirmwareManager(hass)


def test_lan_url_swaps_hostname_for_interface_ip(mgr):
    mgr._lan_source_ip = staticmethod(lambda ip: "192.168.50.20")
    out = asyncio.run(
        mgr._async_lan_url("http://homeassistant.local:8123/home_climate_control_static/firmware/firmware-d1_mini.bin", "192.168.50.153")
    )
    assert out.startswith("http://192.168.50.20:8123/")
    assert out.endswith("/firmware-d1_mini.bin")


def test_lan_url_keeps_base_when_lookup_fails(mgr):
    def boom(ip):
        raise OSError("no route")

    def _failing_job(fn, *a):
        fut = asyncio.get_event_loop().create_future()
        fut.set_exception(boom(*a))
        return fut

    mgr.hass.async_add_executor_job = _failing_job
    base = "http://homeassistant.local:8123/x.bin"
    assert asyncio.run(mgr._async_lan_url(base, "192.168.50.153")) == base


def test_lan_url_keeps_ip_base(mgr):
    mgr._lan_source_ip = staticmethod(lambda ip: "192.168.50.20")
    base = "http://192.168.50.20:8123/x.bin"
    assert asyncio.run(mgr._async_lan_url(base, "192.168.50.153")) == base

