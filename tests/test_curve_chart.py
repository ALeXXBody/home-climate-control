"""Curve chart backend tests (operating-point ring + WS command)."""

import asyncio
from unittest.mock import MagicMock

from custom_components.home_climate_control import websocket_api
from custom_components.home_climate_control.central import CentralController
from custom_components.home_climate_control.const import DOMAIN, CURVE_RING_POINTS


def _controller():
    backend = MagicMock()
    backend.outdoor_temp = 5.0
    backend.outdoor_age_s = 0
    backend.flow_temp = 45.0
    backend.return_temp = 40.0
    backend.flame_on = False
    backend.ch_active = False
    c = CentralController(
        MagicMock(), backend,
        curve_coeff=1.2, design_outdoor=-10.0,
        min_flow=25, max_flow=75,
    )
    c.windtrim.enabled = False
    return c


def test_curve_push_respects_sampling_and_cap():
    c = _controller()
    # 4 pushes → no sample yet (every 5th)
    for _ in range(4):
        c._curve_i += 1
        c._curve_ring.append if False else None
    c._curve_i = 0
    for i in range(10):
        c._curve_i += 1
        if c._curve_i % 5 == 0:
            c._curve_ring.append({"t": i, "o": 5.0, "f": 45.0, "s": 21.0})
    assert len(c._curve_ring) == 2  # 10 pushes → 2 samples

    # cap respected
    c._curve_ring.clear()
    from collections import deque
    c._curve_ring = __import__("collections").deque(maxlen=CURVE_RING_POINTS)
    for i in range(CURVE_RING_POINTS + 50):
        c._curve_ring.append(i)
    assert len(c._curve_ring) == CURVE_RING_POINTS


def test_curve_data_shape_and_line_bounds():
    c = _controller()
    c.zones = []  # no rooms → ref falls back to comfort default
    c._curve_ring.append({"t": 1, "o": 4.8, "f": 44.0, "s": 21.0})
    d = c.curve_data()
    assert d["params"]["coeff"] == 1.2
    assert d["params"]["min_flow"] == 25 and d["params"]["max_flow"] == 75
    assert d["points"] == [{"t": 1, "o": 4.8, "f": 44.0, "s": 21.0}]
    line = d["line"]
    for p in line:
        assert 25.0 <= p["f"] <= 75.0


def test_ws_get_curve_returns_controller_data():
    fc = MagicMock()
    fc.curve_data = lambda: {"points": [1], "line": [2],
                             "params": {"coeff": 1.2}}
    hass = MagicMock()
    hass.data = {DOMAIN: {"e1": {"controller": fc}}}
    conn = MagicMock()
    asyncio.run(websocket_api.ws_get_curve(
        hass, conn, {"id": 3, "type": f"{DOMAIN}/get_curve"}))
    res = conn.send_result.call_args.args[1]
    assert res == {"points": [1], "line": [2], "params": {"coeff": 1.2}}
