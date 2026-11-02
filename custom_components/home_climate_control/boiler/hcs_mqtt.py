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
from datetime import timedelta
import logging
import time

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval

from .base import BoilerBackend

_LOGGER = logging.getLogger(__name__)

DEFAULT_PREFIX = "hcs"


def _f(payload: str | None) -> float | None:
    import math

    try:
        v = float(payload)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _onoff(payload: str) -> bool:
    return str(payload).strip().upper() in ("ON", "1", "TRUE")


class _NodeState:
    """Telemetry cache for one HCS board."""

    __slots__ = (
        "node_id", "last_rx", "online", "ot_valid", "outdoor_temp",
        "outdoor_rx", "flow_temp", "return_temp", "modulation", "pressure",
        "flame", "ch_active", "fault_text", "commanded_setpoint",
        "custom", "sensors_snapshot", "tset_cap",
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
        self.tset_cap: float | None = None  # learned boiler CH ceiling


class HcsMqttBackend(BoilerBackend):
    """Talks to whichever HCS device is alive on the ``hcs/`` tree."""

    CONNECTED_STALE_S = 300  # silent board for 5 min = disconnected
    DEAF_WATCH_INTERVAL = timedelta(minutes=5)
    DEAF_WATCH_INACTIVE_S = 900.0  # 15 min without any leaf = deaf

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
        self._deaf_notified = False
        self._sub_unsubs: list = []
        self._sensors_listeners: list = []
        self._unsubs: list = []
        # ingestion observability: the arrival counter + the last raw topics,
        # surfaced in backend_nodes — the definitive split between "the
        # broker/board never delivered" (counter frozen) and "delivered but
        # mishandled" (counter climbing, topics listed). No guessing anymore.
        self._leaf_count = 0
        self._leaf_topics: list = []

    @callback
    def _dispatch_fn(self, msg) -> None:
        if isinstance(self._leaf_count, int):
            self._leaf_count += 1
            self._leaf_topics = ([*self._leaf_topics[-9:], msg.topic]
                                 if hasattr(self, "_leaf_topics") else [msg.topic])
        self._on_topic(msg.topic, msg.payload)

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

        self._unsubs.append(await self._subscribe_leaves())
        # The hub went deaf for 7 days in 2026-10 while everything else
        # said "connected": the hcs/# subscription died silently at the
        # broker and never recovered. A periodic re-assert (re-subscribe is
        # idempotent and cheap) plus a staleness alarm turns that class
        # into a minutes-scale self-heal.
        self._unsubs.append(
            async_track_time_interval(
                self._hass, self._async_ingest_watchdog,
                HcsMqttBackend.DEAF_WATCH_INTERVAL,
            )
        )
        # Ask every board to re-announce (answers during grace are wiped
        # then re-instantiated after — the post-grace ping re-trigger).
        await mqtt.async_publish(
            self._hass, f"{self._prefix}/discovery/ping", "1", 0, False
        )

    async def _subscribe_leaves(self):
        """Leaf subscription re-assert: unsubscribes the prior handle first
        (each subscribe call registers its own delivery binding)."""
        for un in self._sub_unsubs:
            un()
        self._sub_unsubs.clear()
        un = await mqtt.async_subscribe(
            self._hass, f"{self._prefix}/#", self._dispatch_fn, 0
        )
        self._sub_unsubs.append(un)
        # keep async_stop able to kill whatever is live right now
        self._unsubs = [un]
        return un

    async def _async_ingest_watchdog(self, now=None):
        """Re-assert the leaf subscription; alarm once when nothing lands."""
        st = self._state()
        stale = (
            st is None
            or st.last_rx is None
            or (time.monotonic() - st.last_rx
                > HcsMqttBackend.DEAF_WATCH_INACTIVE_S)
        )
        if self._sub_unsubs_fresh_clare:
            pass
        # re-subscribe every cycle: HA delivers retained leaves at (re)
        # subscribe and the same callback keeps the routing
        await self._subscribe_leaves()
        if stale and not self._deaf_notified:
            self._deaf_notified = True
            try:
                await self._hass.services.async_call(
                    "persistent_notification", "create",
                    {
                        "title": "Board telemetry stalled — MQTT re-asserted",
                        "message": "The hub has not received any board "
                            "telemetry for 15+ minutes. The leaf "
                            "subscription was re-asserted automatically; "
                            "if the boards stay silent after reload, "
                            "restart Home Assistant once to rebuild the "
                            "MQTT session.",
                        "notification_id": "home_climate_control_deaf_watch",
                    },
                    blocking=False,
                )
            except Exception:  # noqa: BLE001
                pass
        elif not stale:
            self._deaf_notified = False

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

    def diagnostics(self) -> dict:
        """Per-node raw view — the get_status surface shows it so a live
        hub/board disagreement (e.g. tset_cap never surfacing while the
        board holds it) is visible from the panel, not guessed at."""
        return {
            "leaf_count": self._leaf_count,
            "leaf_topics": list(self._leaf_topics),
            "nodes": {
                nid: {
                    "online": st.online,
                    "ot_valid": st.ot_valid,
                    "tset_cap": st.tset_cap,
                    "last_rx": (
                        round(st.last_rx, 1) if st.last_rx is not None else None
                    ),
                }
                for nid, st in self._nodes.items()
            }
        }

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
        if key == "tset_cap":
            # Learned CH ceiling from TSet W-ACK echoes ("off" = unknown:
            # the boiler ACKs every request unchanged).
            st.tset_cap = _f(text)
            self._notify_sensors()
            return
        if key == "ctl" and text.startswith("{"):
            # Retained control-state mirror (publishCtl JSON). Carries the
            # learned tset_cap for consumers that gather per-node control
            # state wholesale — this is the retained, guaranteed-delivered
            # channel; the per-leaf q0 topic above is the live one.
            try:
                data = json.loads(text)
            except ValueError:
                return
            raw = data.get("tset_cap")
            v: float | None = None
            if raw not in (None, "null"):
                try:
                    v = float(raw)
                except (TypeError, ValueError):
                    v = None
            if st.tset_cap != v:
                st.tset_cap = v
                self._notify_sensors()
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

    async def async_set_flow_setpoint(self, temp: float, *, force: bool = False) -> None:
        temp = max(self._min_flow, min(self._max_flow, temp))
        temp = round(temp * 2) / 2.0
        st = self._state()
        if st is None:
            # No telemetry yet — track against the preferred board.
            st = self._nodes.setdefault(
                self._preferred, _NodeState(self._preferred)
            )
        if temp == st.commanded_setpoint and not force:
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
    def tset_cap(self):
        """Boiler's real max CH flow setpoint as learned by the board
        (None while the boiler ACKs every request unchanged)."""
        st = self._state()
        return st.tset_cap if st else None

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

    def remove_sensors_listener(self, cb) -> None:
        try:
            self._sensors_listeners.remove(cb)
        except ValueError:
            pass
