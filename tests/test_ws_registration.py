"""Regression gate: EVERY public ws_* handler must be WS-registered.

The Debug tab shipped with ws_get_debug_log defined but never registered,
so the panel got "Unknown command." — a silent class of bug. This test
enumerates all public ws_* coroutine functions in the module and demands
an async_register_command call for each one.
"""

import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock

import custom_components.home_climate_control.websocket_api as wapi


def test_all_public_ws_handlers_are_registered():
    handlers = {
        name: obj
        for name, obj in vars(wapi).items()
        if name.startswith("ws_")
        and inspect.iscoroutinefunction(obj)
        and not name.startswith("ws_mock")
    }
    assert handlers, "no ws_* handlers found — import broken?"

    hass = MagicMock()
    hass.data = {}
    # reading the manifest is executor I/O; make it fail like offline
    hass.async_add_executor_job = AsyncMock(side_effect=OSError)
    asyncio.run(wapi.async_setup_websocket(hass))

    registered = {
        c.args[1].__name__ if c.args and len(c.args) > 1 else None
        for c in wapi.websocket_api.async_register_command.call_args_list
    }
    missing = sorted(set(handlers) - set(registered))
    assert not missing, (
        f"handlers defined but NOT registered (panel would get "
        f"'Unknown command.'): {missing}"
    )


def test_duplicate_registration_is_idempotent():
    """A second setup call (reload) must not double-register (data key)."""
    hass = MagicMock()
    hass.data = {}
    hass.async_add_executor_job = AsyncMock(side_effect=OSError)
    asyncio.run(wapi.async_setup_websocket(hass))
    first = wapi.websocket_api.async_register_command.call_count
    asyncio.run(wapi.async_setup_websocket(hass))
    second = wapi.websocket_api.async_register_command.call_count
    assert first == second, "reload re-registered the WS handlers"
