"""OpenTherm Gateway backend via MQTT (OTGW-firmware).

Telemetry:  <prefix>/<subject>            (e.g. OTGW/outsidetemperature)
Commands:   <prefix>/set/<node-id>/<cmd>  (e.g. OTGW/set/otgw-AABBCCDDEEFF/ctrlsetpt)

Command set (from otgw-firmware MQTTstuff.ino `setcmds`):
  ctrlsetpt    -> CS=<temp>      flow-water control setpoint (0.5 °C steps)
  maxmodulation-> MM=<level>     max relative modulation 0-100
  chenable     -> CH=on/off      central-heating enable
"""

from __future__ import annotations

import logging

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant, callback

from ..const import (
    OTGW_CMD_CH_ENABLE,
    OTGW_CMD_FLOW_SETPOINT,
    OTGW_CMD_MAX_MODULATION,
    OTGW_TOPIC_MAP,
)
from .base import BoilerBackend

_LOGGER = logging.getLogger(__name__)


def _f(payload: str | None) -> float | None:
    try:
        return float(payload)
    except (TypeError, ValueError):
        return None


class OtgwMqttBackend(BoilerBackend):
    """Drives an OpenTherm Gateway through otgw-firmware MQTT."""

    def __init__(
        self,
        hass: HomeAssistant,
        prefix: str,
        node_id: str,
        min_flow: float,
        max_flow: float,
    ) -> None:
        self._hass = hass
        self._prefix = prefix.rstrip("/")
        self._node_id = node_id
        self._min_flow = min_flow
        self._max_flow = max_flow

        self._outdoor_temp: float | None = None
        self._flow_temp: float | None = None
        self._return_temp: float | None = None
        self._modulation: float | None = None
        self._flame: bool | None = None
        self._ch_active: bool | None = None
        self._commanded_setpoint: float | None = None

        self._unsubs: list = []

    # --- topic helpers -------------------------------------------------------
    def _value_topic(self, key: str) -> str:
        return f"{self._prefix}/{OTGW_TOPIC_MAP[key]}"

    def _cmd_topic(self, command: str) -> str:
        return f"{self._prefix}/set/{self._node_id}/{command}"

    # --- lifecycle -----------------------------------------------------------
    async def async_start(self) -> None:
        watches = {
            "outside_temp": self._on_outdoor,
            "flow_temp": self._on_flow,
            "return_temp": self._on_return,
            "modulation_level": self._on_modulation,
            "flame": self._on_flame,
            "ch_active": self._on_ch,
        }
        for subject, handler in watches.items():
            self._unsubs.append(
                await mqtt.async_subscribe(
                    self._hass, self._value_topic(subject), handler, 0
                )
            )
        _LOGGER.info(
            "OTGW backend subscribed under %s (commands to %s)",
            self._prefix,
            f"{self._prefix}/set/{self._node_id}/*",
        )

    async def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    # --- incoming telemetry --------------------------------------------------
    @callback
    def _on_outdoor(self, msg) -> None:
        self._outdoor_temp = _f(msg.payload)

    @callback
    def _on_flow(self, msg) -> None:
        self._flow_temp = _f(msg.payload)

    @callback
    def _on_return(self, msg) -> None:
        self._return_temp = _f(msg.payload)

    @callback
    def _on_modulation(self, msg) -> None:
        self._modulation = _f(msg.payload)

    @callback
    def _on_flame(self, msg) -> None:
        self._flame = str(msg.payload).upper() == "ON"

    @callback
    def _on_ch(self, msg) -> None:
        self._ch_active = str(msg.payload).upper() == "ON"

    # --- commands ------------------------------------------------------------
    async def _publish_cmd(self, command: str, payload: str) -> None:
        await mqtt.async_publish(
            self._hass, self._cmd_topic(command), payload, qos=0, retain=True
        )

    async def async_set_ch_enabled(self, enabled: bool) -> None:
        await self._publish_cmd(OTGW_CMD_CH_ENABLE, "on" if enabled else "off")

    async def async_set_flow_setpoint(self, temp: float) -> None:
        temp = max(self._min_flow, min(self._max_flow, temp))
        temp = round(temp * 2) / 2.0  # OpenTherm TSet granularity is 0.5 °C
        if temp == self._commanded_setpoint:
            return
        await self._publish_cmd(OTGW_CMD_FLOW_SETPOINT, f"{temp:.1f}")
        self._commanded_setpoint = temp
        _LOGGER.debug("Flow setpoint commanded: %.1f °C", temp)

    async def async_set_max_modulation(self, percent: float) -> None:
        await self._publish_cmd(OTGW_CMD_MAX_MODULATION, f"{int(percent)}")

    # --- telemetry -----------------------------------------------------------
    @property
    def outdoor_temp(self) -> float | None:
        return self._outdoor_temp

    @property
    def flow_temp(self) -> float | None:
        return self._flow_temp

    @property
    def return_temp(self) -> float | None:
        return self._return_temp

    @property
    def modulation_level(self) -> float | None:
        return self._modulation

    @property
    def flame_on(self) -> bool | None:
        return self._flame

    @property
    def ch_active(self) -> bool | None:
        return self._ch_active

    def diagnostics(self) -> dict:
        data = super().diagnostics()
        data["commanded_setpoint"] = self._commanded_setpoint
        return data
