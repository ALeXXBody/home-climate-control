"""Blocking-call regression: executor results must be awaited, not re-run inline.

Home Assistant flagged write_text/open/read_text inside the event loop
(2026-11-12). Root cause: _async_blocking only awaited coroutines, but
hass.async_add_executor_job returns a Future — so the guard missed and the
filesystem call ran on the loop (twice: once scheduled, once inline).
"""
import asyncio
from unittest.mock import MagicMock

from custom_components.home_climate_control.firmware_manager import (
    FirmwareManager,
)


def _mgr_with_job(job):
    hass = MagicMock()
    hass.async_add_executor_job = job
    return FirmwareManager(hass)


def test_async_blocking_awaits_future_result():
    """Real-HA-shaped job (returns a Future): func runs once, result returned."""
    calls = []

    def blocking_fn(a, b):
        calls.append((a, b))
        return a + b

    async def main():
        loop = asyncio.get_running_loop()

        def fake_job(func, *args):
            return loop.run_in_executor(None, func, *args)

        mgr = _mgr_with_job(fake_job)
        assert await mgr._async_blocking(blocking_fn, 2, 3) == 5

    asyncio.run(main())
    assert calls == [(2, 3)], f"blocking fn must run exactly once: {calls}"


def test_async_blocking_awaits_coroutine_result():
    """Coroutine-returning job: still awaited."""

    async def blocking_fn():
        return "ok"

    async def main():
        async def fake_job(func, *args):
            return await func(*args)

        mgr = _mgr_with_job(fake_job)
        assert await mgr._async_blocking(blocking_fn) == "ok"

    asyncio.run(main())


def test_async_blocking_magicmock_runs_inline():
    """Unit-test hass double (MagicMock job): direct call, unchanged behaviour."""
    mgr = _mgr_with_job(MagicMock())
    assert asyncio.run(mgr._async_blocking(lambda: 42)) == 42


def test_async_refresh_installed_version_off_loop():
    """The status-path cache refresh uses the executor when one exists."""
    import custom_components.home_climate_control.websocket_api as ws

    async def main():
        loop = asyncio.get_running_loop()
        hass = MagicMock()

        def fake_job(func, *args):
            return loop.run_in_executor(None, func, *args)

        hass.async_add_executor_job = fake_job  # plain function, not a mock
        version = await ws._async_refresh_installed_version(hass)
        assert isinstance(version, str) and version

    asyncio.run(main())
