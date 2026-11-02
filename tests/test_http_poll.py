"""The HTTP-primary poll must run WITHOUT MQTT adoption."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import custom_components.home_climate_control.boiler.hcs_mqtt as mod
from custom_components.home_climate_control.boiler.hcs_mqtt import HcsMqttBackend


def test_watchdog_does_not_touch_a_missing_attribute():
    """v1.25.0 crashed every 5 minutes on a name that was never defined."""
    import asyncio
    import inspect

    src = inspect.getsource(HcsMqttBackend._async_ingest_watchdog)
    assert "_sub_unsubs_fresh_clare" not in src

    backend = HcsMqttBackend(MagicMock(), "hcs-a", 25, 75)
    backend._hass = MagicMock()
    backend._active = None

    async def _sub(*a, **k):
        return lambda: None

    async def _pub(*a, **k):
        return None

    with patch.object(mod.mqtt, "async_subscribe", _sub), patch.object(
        mod.mqtt, "async_publish", _pub
    ):
        asyncio.run(backend._async_ingest_watchdog())


def test_poll_runs_without_adoption_state():
    """The adoption gate (_active=None after a dead MQTT leg) must not block
    the poll — the preferred node gets polled from the entry configuration."""
    backend = HcsMqttBackend(MagicMock(), "hcs-a", 25, 75)
    backend._hass = MagicMock()
    backend._active = None                        # no leaves ever adopted
    calls = []

    async def _fake_poll(nid):
        calls.append(nid)

    backend._async_http_poll_status = _fake_poll
    import asyncio
    asyncio.run(backend._async_http_poll_tick())
    assert calls == ["hcs-a"]                     # the configured node polled


def test_retained_phantom_replay_does_not_adopt_stale_board():
    backend = HcsMqttBackend(MagicMock(), "hcs-a", 25, 75)
    backend._on_value("hcs-c4d8d512d085", "online", "online", retained=True)
    backend._on_value("hcs-c4d8d512d085", "tset_cap", "40", retained=True)
    backend._on_value("hcs-c4d8d512d085", "flow_temp", "20", retained=True)
    assert backend.active_node is None

    backend._on_value("hcs-a", "flow_temp", "55.0")
    assert backend.active_node == "hcs-a"


def test_blank_outdoor_replay_does_not_erase_a_live_reading():
    backend = HcsMqttBackend(MagicMock(), "hcs-a", 25, 75)
    backend._on_value("hcs-a", "outdoor_temp", "8.0")
    backend._on_value("hcs-a", "flow_temp", "55.0")
    backend._on_value("hcs-a", "return_temp", "48.0")
    backend._active = "hcs-a"
    backend._on_value("hcs-a", "outdoor_temp", "")
    backend._on_value("hcs-a", "outdoor_temp", "nan")
    backend._on_value("hcs-a", "flow_temp", "")
    backend._on_value("hcs-a", "return_temp", "off")
    assert backend.outdoor_temp == 8.0
    assert backend.flow_temp == 55.0
    assert backend.return_temp == 48.0


def test_diagnostics_exports_the_fields_the_card_reads():
    """The home card reads these keys off controller.diagnostics(), which
    copies backend.diagnostics(). Missing them is the dash bug."""
    backend = HcsMqttBackend(MagicMock(), "hcs-a", 25, 75)
    st = mod._NodeState("hcs-a")
    st.flow_temp = 55.0
    st.return_temp = 48.2
    st.modulation = 3.0
    st.flame = True
    st.ch_active = True
    st.tset_cap = 55.0
    st.pressure = 1.8
    backend._nodes["hcs-a"] = st
    backend._active = "hcs-a"
    d = backend.diagnostics()
    assert d["flow_temp"] == 55.0
    assert d["return_temp"] == 48.2
    assert d["modulation_level"] == 3.0
    assert d["flame_on"] is True
    assert d["ch_active"] is True
    assert d["tset_cap"] == 55.0
    assert d["pressure_bar"] == 1.8


def test_http_poll_maps_portal_fields_and_adopts():
    import asyncio

    class _Resp:
        status = 200

        async def json(self, content_type=None):
            return {
                "flow_temp": 55, "return_temp": 48.2, "modulation": 3,
                "pressure_bar": 1.8, "tset_cap": "55.0", "flame": True,
                "ch_active": True, "ot_valid": True, "outdoor_temp": 8,
                "version": "1.5.31", "ip": "192.168.50.21",
            }

    class _Session:
        async def get(self, url, **k):
            self.url = url
            return _Resp()

    backend = HcsMqttBackend(MagicMock(), "hcs-a", 25, 75)
    backend._hass = MagicMock()
    backend._active = None
    session = _Session()
    dev = MagicMock(ip="192.168.50.21", version="")
    fmg = MagicMock()
    fmg.devices = {"hcs-a": dev}
    with patch(
        "custom_components.home_climate_control.firmware_manager.get_firmware_manager",
        return_value=fmg,
    ), patch.object(mod, "async_get_clientsession", return_value=session):
        asyncio.run(backend._async_http_poll_status("hcs-a"))
    st = backend._nodes["hcs-a"]
    assert st.flow_temp == 55.0
    assert st.return_temp == 48.2
    assert st.modulation == 3.0
    assert st.pressure == 1.8
    assert st.tset_cap == 55.0
    assert backend._active == "hcs-a"
    assert backend.diagnostics()["flow_temp"] == 55.0
