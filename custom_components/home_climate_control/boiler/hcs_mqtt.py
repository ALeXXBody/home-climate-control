"""Native Home Climate System device backend via MQTT.

Follows the **board that is actually alive**, not a hard-coded node id:

- subscribes to the whole ``hcs/#`` tree
- the node id chosen at setup is *preferred* while it publishes telemetry
- when that board is gone (LWT ``offline`` or silent), any other HCS board
  publishing telemetry takes over automatically — a swapped or re-flashed
  board keeps HCC working without touching the config

Telemetry:  hcs/<node>/<key>          (e.g. hcs/hcs-aabbcc/outdoor_temp)
Commands:   hcs/<node>/set/<cmd>      (e.g. hcs/hcs-aabbcc/set/flow_setpoint)
"""

from __future__ import annotations

import json
import logging
import time

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant, callback

from .base import BoilerBackend

_LOGGER = logging.getLogger(__name__)

DEFAULT_PREFIX = "hcs"


def _f(payload: str | None) -> float | None:
    try:
        return float(payload)
    except (TypeError, ValueError):
        return None


def _onoff(payload: str) -> bool:
    return str(payload).strip().upper() in ("ON", "1", "TRUE")


class _NodeState:
    """Telemetry cache for one HCS board."""

    __slots__ = (
        "node_id", "last_rx", "online", "ot_valid", "outdoor_temp",
        "outdoor_rx", "flow_temp", "return_temp", "modulation", "pressure",
        "flame", "ch_active", "fault_text", "commanded_setpoint",
        "custom", "sensors_snapshot",
    )

    def __init__(self, node_id: str) -> None:
        self.node_id = node_id
        self.last_rx: float | None = None
        self.online: bool | None = None
        self.ot_valid: bool | None = None
        self.outdoor_temp: float | None = None
        self.outdoor_rx: float | None = None
        self.flow_temp: float | None = None
        self.return_temp: float | None = None
        self.modulation: float | None = None
        self.pressure: float | None = None
        self.flame: bool | None = None
        self.ch_active: bool | None = None
        self.fault_text: str | None = None
        self.commanded_setpoint: float | None = None
        self.custom: dict[str, float] = {}
        self.sensors_snapshot: list = []


class HcsMqttBackend(BoilerBackend):
    """Talks to whichever HCS device is alive on the ``hcs/`` tree."""

    CONNECTED_STALE_S = 300  # silent board for 5 min = disconnected

    def __init__(
        self,
        hass: HomeAssistant,
        node_id: str,
        min_flow: float,
        max_flow: float,
        prefix: str = DEFAULT_PREFIX,
    ) -> None:
        self._hass = hass
        self._preferred = node_id
        self._prefix = prefix.rstrip("/")
        self._min_flow = min_flow
        self._max_flow = max_flow

        self._nodes: dict[str, _NodeState] = {}
        self._active: str | None = None

        self._sensors_listeners: list = []
        self._unsubs: list = []

    # --- topics --------------------------------------------------------------
    @property
    def base(self) -> str:
        return f"{self._prefix}/{self._active or self._preferred}"

    @property
    def active_node(self) -> str | None:
        return self._active

    def _cmd_topic(self, command: str) -> str:
        return f"{self.base}/set/{command}"

    def _state(self, node: str | None = None) -> _NodeState | None:
        nid = node or self._active
        return self._nodes.get(nid) if nid else None

    # --- lifecycle -----------------------------------------------------------
    async def async_start(self) -> None:
        @callback
        def _dispatch(msg) -> None:
            self._on_topic(msg.topic, msg.payload)

        self._unsubs.append(
            await mqtt.async_subscribe(self._hass, f"{self._prefix}/#", _dispatch, 0)
        )
        # Ask every board to re-announce itself.
        await mqtt.async_publish(
            self._hass, f"{self._prefix}/discovery/ping", "1", 0, False
        )
        _LOGGER.info(
            "HCS backend watching %s/# (prefers %s, any live board accepted)",
            self._prefix,
            self._preferred,
        )

    async def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    # --- dispatch ------------------------------------------------------------
    @callback
    def _on_topic(self, topic: str, payload) -> None:
        text = (
            payload if isinstance(payload, str)
            else payload.decode("utf-8", "replace")
            if isinstance(payload, (bytes, bytearray))
            else str(payload or "")
        ).strip()
        rest = topic[len(self._prefix) + 1 :] if topic.startswith(self._prefix + "/") else topic

        if rest.startswith("discovery"):
            return  # discovery JSON handled by the firmware manager
        node, _, key = rest.partition("/")
        if not node or not key:
            return
        self._on_value(node, key, text)

    @callback
    def _on_value(self, node: str, key: str, text: str) -> None:
        st = self._nodes.get(node)
        if st is None:
            st = self._nodes[node] = _NodeState(node)

        if key == "online":
            low = text.lower()
            if low in ("offline", "0", "false"):
                st.online = False
            elif low in ("online", "1", "true", "on"):
                st.online = True
                st.last_rx = time.monotonic()  # LWT online = board alive
            self._maybe_adopt(st)
            return
        if key == "ping_discovery" or key.startswith("set/"):
            return

        # Any live telemetry leaf is a heartbeat for this node.
        st.last_rx = time.monotonic()
        self._maybe_adopt(st)

        if key.startswith("x/"):
            name = key[2:].strip()
            if name:
                v = _f(text)
                if v is not None:
                    st.custom[name] = v
                    self._notify_sensors()
            return
        if key == "sensors":
            try:
                data = json.loads(text) if text else {}
                devices = data.get("devices") if isinstance(data, dict) else data
                if isinstance(devices, list):
                    st.sensors_snapshot = devices
                    for d in devices:
                        if isinstance(d, dict) and d.get("role") == "custom" and d.get("name"):
                            t = d.get("temp_c")
                            if t is not None:
                                try:
                                    st.custom[str(d["name"])] = float(t)
                                except (TypeError, ValueError):
                                    pass
                    self._notify_sensors()
            except Exception:  # noqa: BLE001
                pass
            return
        if key == "ot_valid":
            st.ot_valid = _onoff(text)
            return
        if key == "outdoor_temp":
            st.outdoor_temp = _f(text)
            if st.outdoor_temp is not None:
                st.outdoor_rx = time.monotonic()
        elif key == "flow_temp":
            st.flow_temp = _f(text)
        elif key == "return_temp":
            st.return_temp = _f(text)
        elif key == "modulation":
            v = _f(text)
            st.modulation = v / 256.0 * 100 if v and v > 100 else v
        elif key == "ch_pressure":
            st.pressure = _f(text)
        elif key == "flame":
            st.flame = _onoff(text)
        elif key == "ch_active":
            st.ch_active = _onoff(text)
        elif key == "boiler_diag":
            st.fault_text = text

    # --- board adoption ------------------------------------------------------
    def _maybe_adopt(self, st: _NodeState) -> None:
        """Follow the preferred board while it lives; else any live board."""
        if st.node_id == self._active:
            return
        live = st.online is not False and (
            st.last_rx is None or time.monotonic() - st.last_rx <= 30
        )
        if st.node_id == self._preferred:
            if live:
                self._switch(st)
            return
        # Non-preferred board: only take over when the current one is dead.
        cur = self._state()
        cur_dead = (
            cur is None
            or cur.online is False
            or cur.last_rx is None
            or time.monotonic() - cur.last_rx > 60
        )
        if live and cur_dead and st.last_rx is not None:
            self._switch(st)

    def _switch(self, st: _NodeState) -> None:
        old = self._active
        self._active = st.node_id
        if old != st.node_id:
            _LOGGER.info(
                "HCS backend now following board %s (was %s; configured %s)",
                st.node_id, old, self._preferred,
            )
        self._notify_sensors()

    def _notify_sensors(self) -> None:
        for cb in list(self._sensors_listeners):
            try:
                cb()
            except Exception:  # noqa: BLE001
                pass

    # --- commands ------------------------------------------------------------
    async def _publish_cmd(self, command: str, payload: str, retain=False) -> None:
        # Commands must not be retained: a retained CH-on after HA unload can
        # re-fire the boiler when the board reboots without HA connected.
        await mqtt.async_publish(
            self._hass, self._cmd_topic(command), payload, qos=0, retain=retain
        )

    async def async_set_ch_enabled(self, enabled: bool) -> None:
        await self._publish_cmd("ch_enable", "on" if enabled else "off")

    async def async_set_flow_setpoint(self, temp: float) -> None:
        temp = max(self._min_flow, min(self._max_flow, temp))
        temp = round(temp * 2) / 2.0
        st = self._state()
        if st is None:
            # No telemetry yet — track against the preferred board.
            st = self._nodes.setdefault(
                self._preferred, _NodeState(self._preferred)
            )
        if temp == st.commanded_setpoint:
            return
        await self._publish_cmd("flow_setpoint", f"{temp:.1f}")
        st.commanded_setpoint = temp
        _LOGGER.debug("Flow setpoint commanded: %.1f °C", temp)

    async def async_set_failsafe_cfg(
        self, enable: bool, flow: float, grace_min: int
    ) -> None:
        payload = json.dumps(
            {"enable": bool(enable), "flow": float(flow), "grace_min": int(grace_min)}
        )
        await self._publish_cmd("failsafe_cfg", payload)

    async def async_set_max_modulation(self, percent: float) -> None:
        await self._publish_cmd("max_modulation", f"{int(percent)}")

    # --- telemetry properties (active board) ---------------------------------
    @property
    def outdoor_temp(self):
        st = self._state()
        return st.outdoor_temp if st else None

    @property
    def outdoor_age_s(self) -> float | None:
        st = self._state()
        if st is None or st.outdoor_rx is None or st.outdoor_temp is None:
            return None
        return max(0.0, time.monotonic() - st.outdoor_rx)

    @property
    def flow_temp(self):
        st = self._state()
        return st.flow_temp if st else None

    @property
    def return_temp(self):
        st = self._state()
        return st.return_temp if st else None

    @property
    def modulation_level(self):
        st = self._state()
        return st.modulation if st else None

    @property
    def flame_on(self):
        st = self._state()
        return st.flame if st else None

    @property
    def ch_active(self):
        st = self._state()
        return st.ch_active if st else None

    @property
    def pressure_bar(self):
        st = self._state()
        return st.pressure if st else None

    @property
    def fault_text(self):
        st = self._state()
        return st.fault_text if st else None

    @property
    def connected(self):
        """Active board's MQTT link (not the OpenTherm bus).

        - False: LWT offline, or no telemetry for CONNECTED_STALE_S
        - True: recent telemetry
        - None: nothing received yet
        """
        st = self._state()
        if st is None:
            return None
        if st.online is False:
            return False
        if st.last_rx is None:
            return None
        return (time.monotonic() - st.last_rx) <= self.CONNECTED_STALE_S

    @property
    def ot_valid(self) -> bool | None:
        """OpenTherm bus link as reported by the active board."""
        st = self._state()
        return st.ot_valid if st else None

    def custom_sensors(self) -> dict:
        st = self._state()
        return dict(st.custom) if st else {}

    def sensors_snapshot(self) -> list:
        st = self._state()
        return list(st.sensors_snapshot) if st else []

    def add_sensors_listener(self, cb) -> None:
        if cb not in self._sensors_listeners:
            self._sensors_listeners.append(cb)
