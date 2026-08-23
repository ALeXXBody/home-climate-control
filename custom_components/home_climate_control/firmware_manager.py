"""Discover HCS devices via MQTT and trigger OTA from the Firmware tab."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

DISCOVERY_PREFIX = "hcs/discovery/"
DISCOVERY_PING = "hcs/discovery/ping"
# Drop devices not seen for this long (seconds)
STALE_AFTER = 120

# Bundled / published firmware catalog (GitHub releases or manual URLs)
_RELEASE = "https://github.com/ALeXXBody/home-climate-system/releases/download/v0.5.0"
DEFAULT_CATALOG: list[dict[str, str]] = [
    {
        "id": "hcs-0.5.0-d1_mini",
        "version": "0.5.0",
        "board": "d1_mini",
        "title": "HCS 0.5.0 — ESP8266 D1 mini",
        "url": f"{_RELEASE}/firmware-d1_mini.bin",
        "notes": "OpenTherm master; weather comp; portal + OTA",
    },
    {
        "id": "hcs-0.5.0-lolin_s2_mini",
        "version": "0.5.0",
        "board": "lolin_s2_mini",
        "title": "HCS 0.5.0 — LOLIN S2 mini",
        "url": f"{_RELEASE}/firmware-lolin_s2_mini.bin",
        "notes": "OpenTherm master (stacked); weather comp; portal + OTA",
    },
    {
        "id": "hcs-0.5.0-lolin_c3_mini",
        "version": "0.5.0",
        "board": "lolin_c3_mini",
        "title": "HCS 0.5.0 — LOLIN C3 mini v2.1",
        "url": f"{_RELEASE}/firmware-lolin_c3_mini.bin",
        "notes": "Direct shield fitment (OT GPIO7/6); weather comp; portal + OTA",
    },
    {
        "id": "hcs-0.5.0-esp32_d1_mini",
        "version": "0.5.0",
        "board": "esp32_d1_mini",
        "title": "HCS 0.5.0 — ESP32 D1 mini",
        "url": f"{_RELEASE}/firmware-esp32_d1_mini.bin",
        "notes": "OpenTherm master; weather comp; portal + OTA",
    },
    {
        "id": "hcs-0.5.0-esp32s3_zero",
        "version": "0.5.0",
        "board": "esp32s3_zero",
        "title": "HCS 0.5.0 — ESP32-S3-Zero",
        "url": f"{_RELEASE}/firmware-esp32s3_zero.bin",
        "notes": "Extra target (jumper wires); weather comp; portal + OTA",
    },
    {
        "id": "hcs-0.5.0-gw-lolin_s2_mini",
        "version": "0.5.0",
        "board": "lolin_s2_mini_gw",
        "title": "HCS 0.5.0 GW — LOLIN S2 mini (gateway)",
        "url": f"{_RELEASE}/firmware-lolin_s2_mini_gw.bin",
        "notes": "Gateway build (HCS_GW_ENABLE): OT 4/5 + tstat tap 16/17",
    },
    {
        "id": "hcs-0.5.0-gw-esp32_d1_mini",
        "version": "0.5.0",
        "board": "esp32_d1_mini_gw",
        "title": "HCS 0.5.0 GW — ESP32 D1 mini (gateway)",
        "url": f"{_RELEASE}/firmware-esp32_d1_mini_gw.bin",
        "notes": "Gateway build (HCS_GW_ENABLE): OT 21/22 + tstat tap 26/27",
    },
    {
        "id": "hcs-0.5.0-gw-lolin_c3_mini",
        "version": "0.5.0",
        "board": "lolin_c3_mini_gw",
        "title": "HCS 0.5.0 GW — LOLIN C3 mini v2.1 (gateway)",
        "url": f"{_RELEASE}/firmware-lolin_c3_mini_gw.bin",
        "notes": "Gateway build (HCS_GW_ENABLE): OT 7/6 + tstat tap 4/5",
    },
]


def catalog_item(catalog: list[dict[str, str]], catalog_id: str) -> dict | None:
    for item in catalog:
        if item.get("id") == catalog_id:
            return item
    return None


@dataclass
class HcsDevice:
    node_id: str
    name: str = ""
    board: str = ""
    version: str = ""
    ip: str = ""
    ota_http: str = ""
    api_status: str = ""
    api_ota: str = ""
    online: bool = True
    last_seen: str = ""
    last_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FirmwareManager:
    """Tracks HCS devices from MQTT discovery messages."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.devices: dict[str, HcsDevice] = {}
        self._unsub = None
        self.catalog: list[dict[str, str]] = list(DEFAULT_CATALOG)

    async def async_start(self) -> None:
        if self._unsub is not None:
            return
        self._unsub = await mqtt.async_subscribe(
            self.hass, f"{DISCOVERY_PREFIX}+", self._on_discovery, 0
        )
        # Ask devices to announce themselves
        await mqtt.async_publish(self.hass, DISCOVERY_PING, "1", 0, False)
        _LOGGER.info("Firmware manager listening on %s+", DISCOVERY_PREFIX)

    async def async_stop(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None

    @callback
    def _on_discovery(self, msg) -> None:
        try:
            payload = msg.payload
            if isinstance(payload, bytes):
                payload = payload.decode("utf-8", errors="replace")
            if not payload or payload == "offline":
                # retained clear
                node = msg.topic.rsplit("/", 1)[-1]
                if node in self.devices:
                    self.devices[node].online = False
                return
            data = json.loads(payload)
        except (json.JSONDecodeError, UnicodeError) as err:
            _LOGGER.debug("bad discovery payload: %s", err)
            return

        node = data.get("node_id") or msg.topic.rsplit("/", 1)[-1]
        ip = data.get("ip") or ""
        dev = self.devices.get(node) or HcsDevice(node_id=node)
        dev.name = data.get("name") or dev.name or node
        dev.board = data.get("board") or dev.board
        dev.version = data.get("version") or dev.version
        dev.ip = ip or dev.ip
        dev.ota_http = data.get("ota_http") or (
            f"http://{ip}/update" if ip else dev.ota_http
        )
        dev.api_status = data.get("api_status") or (
            f"http://{ip}/api/status" if ip else dev.api_status
        )
        dev.api_ota = data.get("api_ota") or (
            f"http://{ip}/api/ota" if ip else dev.api_ota
        )
        dev.online = True
        dev.last_seen = datetime.now(timezone.utc).isoformat()
        self.devices[node] = dev

    def list_devices(self) -> list[dict[str, Any]]:
        return [d.to_dict() for d in self.devices.values()]

    async def async_ping(self) -> None:
        await mqtt.async_publish(self.hass, DISCOVERY_PING, "1", 0, False)

    async def async_trigger_ota(
        self, node_id: str, url: str
    ) -> dict[str, Any]:
        """Tell device to pull firmware from URL (MQTT + HTTP fallback)."""
        dev = self.devices.get(node_id)
        if not dev:
            return {"ok": False, "error": "unknown device"}
        if not url:
            return {"ok": False, "error": "missing url"}

        # 1) MQTT command (device handles hcs/<node>/set/ota_url)
        topic = f"hcs/{node_id}/set/ota_url"
        await mqtt.async_publish(self.hass, topic, url, 0, False)
        _LOGGER.info("OTA MQTT %s -> %s", node_id, url)

        # 2) HTTP POST fallback
        http_ok = False
        http_err = ""
        if dev.api_ota or dev.ip:
            api = dev.api_ota or f"http://{dev.ip}/api/ota"
            session = async_get_clientsession(self.hass)
            try:
                async with session.post(
                    api,
                    json={"url": url},
                    timeout=30,
                ) as resp:
                    http_ok = resp.status < 300
                    if not http_ok:
                        http_err = f"HTTP {resp.status}"
            except Exception as err:  # noqa: BLE001
                http_err = str(err)
                _LOGGER.warning("OTA HTTP to %s failed: %s", api, err)

        dev.last_error = http_err
        return {
            "ok": True,
            "mqtt": True,
            "http": http_ok,
            "http_error": http_err or None,
            "node_id": node_id,
            "url": url,
        }

    async def async_reboot(self, node_id: str) -> dict[str, Any]:
        await mqtt.async_publish(
            self.hass, f"hcs/{node_id}/set/reboot", "1", 0, False
        )
        return {"ok": True}


def get_firmware_manager(hass: HomeAssistant) -> FirmwareManager | None:
    return hass.data.get(DOMAIN, {}).get("firmware_manager")


async def async_setup_firmware_manager(hass: HomeAssistant) -> FirmwareManager:
    store = hass.data.setdefault(DOMAIN, {})
    mgr = store.get("firmware_manager")
    if mgr is None:
        mgr = FirmwareManager(hass)
        store["firmware_manager"] = mgr
        await mgr.async_start()
    return mgr
