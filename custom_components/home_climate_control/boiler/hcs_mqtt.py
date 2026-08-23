"""Native Home Climate System device backend via MQTT.

Telemetry:  hcs/<node>/<key>          (e.g. hcs/hcs-aabbcc/outdoor_temp)
Commands:   hcs/<node>/set/<cmd>      (e.g. hcs/hcs-aabbcc/set/flow_setpoint)

This is the first-class and ONLY MQTT contract of HCS devices. The firmware
publishes every value here natively; there is no third-party gateway in the
path.
"""

from __future__ import annotations

import json
import logging

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


class HcsMqttBackend(BoilerBackend):
    """Talks to an HCS device on its native `hcs/<node>/…` topics."""

    def __init__(
        self,
        hass: HomeAssistant,
        node_id: str,
        min_flow: float,
        max_flow: float,
        prefix: str = DEFAULT_PREFIX,
    ) -> None:
        self._hass = hass
        self._node_id = node_id
        self._prefix = prefix.rstrip("/")
        self._min_flow = min_flow
        self._max_flow = max_flow

        self._outdoor_temp: float | None = None
        self._flow_temp: float | None = None
        self._return_temp: float | None = None
        self._modulation: float | None = None
        self._pressure: float | None = None
        self._flame: bool | None = None
        self._ch_active: bool | None = None
        self._fault_text: str | None = None
        self._commanded_setpoint: float | None = None

        self._unsubs: list = []

    # --- topics --------------------------------------------------------------
    @property
    def base(self) -> str:
        return f"{self._prefix}/{self._node_id}"

    def _cmd_topic(self, command: str) -> str:
        return f"{self.base}/set/{command}"

    # --- lifecycle -----------------------------------------------------------
    async def async_start(self) -> None:
        @callback
        def _dispatch(msg) -> None:
            suffix = msg.topic[len(self.base) + 1 :]
            self._on_value(suffix, msg.payload)

        self._unsubs.append(
            await mqtt.async_subscribe(
                self._hass, f"{self.base}/#", _dispatch, 0
            )
        )
        await mqtt.async_publish(
            self._hass, f"{self.base}/ping_discovery", "1", 0, False
        )
        _LOGGER.info(
            "HCS backend subscribed to %s/# (commands under %s)",
            self.base,
            f"{self.base}/set/*",
        )

    async def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    # --- telemetry dispatch --------------------------------------------------
    @callback
    def _on_value(self, key: str, payload: str) -> None:
        if "/" in key or key in ("online", "ping_discovery"):
            return  # set-topics & LWT noise
        text = (payload or "").strip()
        if key == "outdoor_temp":
            self._outdoor_temp = _f(text)
        elif key == "flow_temp":
            self._flow_temp = _f(text)
        elif key == "return_temp":
            self._return_temp = _f(text)
        elif key == "modulation":
            v = _f(text)
            self._modulation = v / 256.0 * 100 if v and v > 100 else v
        elif key == "ch_pressure":
            self._pressure = _f(text)
        elif key == "flame":
            self._flame = _onoff(text)
        elif key == "ch_active":
            self._ch_active = _onoff(text)
        elif key == "boiler_diag":
            self._fault_text = text

    # --- commands ------------------------------------------------------------
    async def _publish_cmd(self, command: str, payload: str, retain=True) -> None:
        await mqtt.async_publish(
            self._hass, self._cmd_topic(command), payload, qos=0, retain=retain
        )

    async def async_set_ch_enabled(self, enabled: bool) -> None:
        await self._publish_cmd("ch_enable", "on" if enabled else "off")

    async def async_set_flow_setpoint(self, temp: float) -> None:
        temp = max(self._min_flow, min(self._max_flow, temp))
        temp = round(temp * 2) / 2.0
        if temp == self._commanded_setpoint:
            return
        await self._publish_cmd("flow_setpoint", f"{temp:.1f}")
        self._commanded_setpoint = temp
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

    # --- telemetry properties -------------------------------------------------
    @property
    def outdoor_temp(self): return self._outdoor_temp
    @property
    def flow_temp(self): return self._flow_temp
    @property
    def return_temp(self): return self._return_temp
    @property
    def modulation_level(self): return self._modulation
    @property
    def flame_on(self): return self._flame
    @property
    def ch_active(self): return self._ch_active
    @property
    def pressure_bar(self): return self._pressure
    @property
    def fault_text(self): return self._fault_text

    def diagnostics(self) -> dict:
        data = super().diagnostics()
        data.update(
            commanded_setpoint=self._commanded_setpoint,
            pressure_bar=self._pressure,
            fault_text=self._fault_text,
        )
        return data
