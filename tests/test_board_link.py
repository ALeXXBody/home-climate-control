"""Explicit one-installation-to-one-board binding."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.home_climate_control.const import DOMAIN
from custom_components.home_climate_control.websocket_api import (
    ws_link_board,
    ws_unlink_board,
)


def _entry(node_id="hcs-a", entry_id="entry-1"):
    return SimpleNamespace(
        entry_id=entry_id,
        data={"backend": "hcs", "node_id": node_id, "name": "Home Climate"},
    )


def _hass(entries):
    hm = SimpleNamespace()
    hm.async_entries = MagicMock(return_value=entries)

    def _update(entry, **kwargs):
        entry.data = kwargs.get("data", entry.data)

    hm.async_update_entry = MagicMock(side_effect=_update)
    hm.async_reload = AsyncMock(return_value=True)
    return SimpleNamespace(config_entries=hm)


def _run(coro):
    return asyncio.run(coro)


def test_bound_board_cannot_be_silently_replaced():
    entry = _entry("hcs-a")
    hass = _hass([entry])
    mgr = SimpleNamespace(devices={"hcs-a": MagicMock(), "hcs-b": MagicMock()})
    conn = MagicMock()
    with patch(
        "custom_components.home_climate_control.websocket_api.async_setup_firmware_manager",
        AsyncMock(return_value=mgr),
    ):
        _run(ws_link_board(hass, conn,
                           {"id": 1, "node_id": "hcs-b"}))
    conn.send_error.assert_called_once()
    assert conn.send_error.call_args.args[1] == "board_already_linked"
    assert entry.data["node_id"] == "hcs-a"
    hass.config_entries.async_reload.assert_not_awaited()


def test_unlink_allows_linking_a_replacement():
    entry = _entry("hcs-a")
    hass = _hass([entry])
    mgr = SimpleNamespace(devices={"hcs-a": MagicMock(), "hcs-b": MagicMock()})
    conn = MagicMock()
    with patch(
        "custom_components.home_climate_control.websocket_api.async_setup_firmware_manager",
        AsyncMock(return_value=mgr),
    ):
        _run(ws_unlink_board(hass, conn, {"id": 1}))
        assert entry.data["node_id"] == ""
        _run(ws_link_board(hass, conn,
                           {"id": 2, "node_id": "hcs-b"}))
    assert entry.data["node_id"] == "hcs-b"
    assert hass.config_entries.async_reload.await_count == 2


def test_link_rejects_an_undiscovered_board():
    entry = _entry("")
    hass = _hass([entry])
    mgr = SimpleNamespace(devices={"hcs-b": MagicMock()})
    conn = MagicMock()
    with patch(
        "custom_components.home_climate_control.websocket_api.async_setup_firmware_manager",
        AsyncMock(return_value=mgr),
    ):
        _run(ws_link_board(hass, conn,
                           {"id": 1, "node_id": "hcs-nope"}))
    conn.send_error.assert_called_once()
    assert conn.send_error.call_args.args[1] == "unknown_node"


def test_unbound_backend_does_not_publish_commands():
    from unittest.mock import AsyncMock as AsyncMockClass

    from custom_components.home_climate_control.boiler.hcs_mqtt import HcsMqttBackend

    backend = HcsMqttBackend(MagicMock(), "", 25, 75)
    with patch(
        "custom_components.home_climate_control.boiler.hcs_mqtt.mqtt.async_publish",
        AsyncMockClass(),
    ) as pub:
        _run(backend.async_set_flow_setpoint(55.0, force=True))
    pub.assert_not_awaited()
