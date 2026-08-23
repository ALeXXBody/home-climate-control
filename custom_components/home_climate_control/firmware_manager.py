"""Discover HCS devices via MQTT and trigger OTA from the Firmware tab."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_NODE_ID, DOMAIN

_LOGGER = logging.getLogger(__name__)

DISCOVERY_PREFIX = "hcs/discovery/"
DISCOVERY_PING = "hcs/discovery/ping"
# Drop devices not seen for this long (seconds)
STALE_AFTER = 120

# Bundled / published firmware catalog (GitHub releases or manual URLs)
_RELEASE = "https://github.com/ALeXXBody/home-climate-system/releases/download/v1.0.2"
DEFAULT_CATALOG: list[dict[str, str]] = [
    {
        "id": "hcs-1.0.2-d1_mini",
        "version": "1.0.2",
        "board": "d1_mini",
        "description": "ESP8266 · Wi-Fi 4 · 4 MB flash · the classic budget board",
        "image": "/home_climate_control_static/boards/photos/d1_mini.jpg",
        "model": "D1 mini (ESP8266)",
        "title": "HCS 1.0.2 — ESP8266 D1 mini",
        "url": f"{_RELEASE}/firmware-d1_mini.bin",
        "notes": "OpenTherm master; weather comp; portal + OTA",
    },
    {
        "id": "hcs-1.0.2-lolin_s2_mini",
        "version": "1.0.2",
        "board": "lolin_s2_mini",
        "description": "ESP32-S2 · single core · USB-OTG · 4 MB flash",
        "image": "/home_climate_control_static/boards/photos/lolin_s2_mini.jpg",
        "model": "LOLIN S2 mini",
        "title": "HCS 1.0.2 — LOLIN S2 mini",
        "url": f"{_RELEASE}/firmware-lolin_s2_mini.bin",
        "notes": "OpenTherm master (stacked); weather comp; portal + OTA",
    },
    {
        "id": "hcs-1.0.2-lolin_c3_mini",
        "version": "1.0.2",
        "board": "lolin_c3_mini",
        "description": "ESP32-C3 · RISC-V · USB-C · direct DIYLess shield fitment",
        "image": "/home_climate_control_static/boards/photos/lolin_c3_mini.jpg",
        "model": "LOLIN C3 mini v2.1",
        "title": "HCS 1.0.2 — LOLIN C3 mini v2.1",
        "url": f"{_RELEASE}/firmware-lolin_c3_mini.bin",
        "notes": "Direct shield fitment (OT GPIO7/6); weather comp; portal + OTA",
    },
    {
        "id": "hcs-1.0.2-esp32_d1_mini",
        "version": "1.0.2",
        "board": "esp32_d1_mini",
        "model": "ESP32 D1 mini",
        "description": "ESP32 dual-core · Bluetooth + Wi-Fi · D1-mini footprint",
        "image": "/home_climate_control_static/boards/esp32_d1_mini.svg",
        "title": "HCS 1.0.2 — ESP32 D1 mini",
        "url": f"{_RELEASE}/firmware-esp32_d1_mini.bin",
        "notes": "OpenTherm master; weather comp; portal + OTA",
    },
    {
        "id": "hcs-1.0.2-esp32s3_zero",
        "version": "1.0.2",
        "board": "esp32s3_zero",
        "description": "ESP32-S3 · dual-core LX7 · vector instructions · tiny footprint",
        "image": "/home_climate_control_static/boards/photos/esp32s3_zero.jpg",
        "model": "ESP32-S3-Zero",
        "title": "HCS 1.0.2 — ESP32-S3-Zero",
        "url": f"{_RELEASE}/firmware-esp32s3_zero.bin",
        "notes": "Extra target (jumper wires); weather comp; portal + OTA",
    },
    {
        "id": "hcs-1.0.2-gw-lolin_s2_mini",
        "version": "1.0.2",
        "board": "lolin_s2_mini_gw",
        "description": "",
        "image": "/home_climate_control_static/boards/photos/lolin_s2_mini.jpg",
        "title": "HCS 1.0.2 GW — LOLIN S2 mini (gateway)",
        "url": f"{_RELEASE}/firmware-lolin_s2_mini_gw.bin",
        "notes": "Gateway build (HCS_GW_ENABLE): OT 4/5 + tstat tap 16/17",
    },
    {
        "id": "hcs-1.0.2-gw-esp32_d1_mini",
        "version": "1.0.2",
        "board": "esp32_d1_mini_gw",
        "description": "",
        "image": "/home_climate_control_static/boards/esp32_d1_mini_gw.svg",
        "title": "HCS 1.0.2 GW — ESP32 D1 mini (gateway)",
        "url": f"{_RELEASE}/firmware-esp32_d1_mini_gw.bin",
        "notes": "Gateway build (HCS_GW_ENABLE): OT 21/22 + tstat tap 26/27",
    },
    {
        "id": "hcs-1.0.2-gw-lolin_c3_mini",
        "version": "1.0.2",
        "board": "lolin_c3_mini_gw",
        "description": "",
        "image": "/home_climate_control_static/boards/photos/lolin_c3_mini.jpg",
        "title": "HCS 1.0.2 GW — LOLIN C3 mini v2.1 (gateway)",
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
        self._hass = hass
        self._check_task = None
        self.hass = hass
        self.devices: dict[str, HcsDevice] = {}
        self._flowed_nodes: set[str] = set()
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

    DEVICE_TTL = 600  # seconds; boards announce every ~30 s when online

    def _prune_stale(self) -> None:
        """Forget boards that stopped announcing.

        Retained discovery messages otherwise keep powered-off boards listed
        forever. Live boards re-announce within seconds, so pruning is safe;
        a board that powers back on re-registers instantly.
        """
        now = datetime.now(timezone.utc)
        for node in list(self.devices):
            dev = self.devices[node]
            try:
                seen = datetime.fromisoformat(dev.last_seen)
            except (ValueError, TypeError):
                continue
            if (now - seen).total_seconds() > self.DEVICE_TTL:
                _LOGGER.debug("pruning stale device %s", node)
                del self.devices[node]

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
        self._prune_stale()

        # Re-check (debounced) when a device announces a version — but skip
        # during post-install cooldown so reboot churn does not thrash HA.
        if data.get("version") and self._hass:
            try:
                from .update_checker import get_update_checker

                uc = get_update_checker(self._hass)
                if uc is not None and uc._in_install_cooldown():
                    pass
                else:
                    self._hass.async_create_task(self._trigger_update_check())
            except Exception:  # noqa: BLE001
                self._hass.async_create_task(self._trigger_update_check())

        # HA discovery: surface a setup card for boards that are not yet
        # claimed by any config entry (once per node).
        try:
            claimed = {
                e.data.get(CONF_NODE_ID)
                for e in self._hass.config_entries.async_entries(DOMAIN)
                if getattr(e, "data", None)
            }
            if node not in claimed and node not in self._flowed_nodes:
                self._flowed_nodes.add(node)
                self._hass.async_create_task(
                    self._hass.config_entries.flow.async_init(
                        DOMAIN,
                        context={"source": "discovery"},
                        data={"node_id": node},
                    )
                )
        except Exception:  # noqa: BLE001 - stubbed hass in unit tests
            pass

    def list_devices(self) -> list[dict[str, Any]]:
        return [d.to_dict() for d in self.devices.values()]

    async def _trigger_update_check(self) -> None:
        """Debounced re-check so discovery bursts cause one run."""
        import asyncio

        from .update_checker import get_update_checker

        uc = get_update_checker(self._hass)
        if uc is None:
            return
        if self._check_task:
            return  # already pending
        self._check_task = asyncio.ensure_future(self._debounced_check(uc))

    async def _debounced_check(self, uc) -> None:
        import asyncio

        await asyncio.sleep(5)
        self._check_task = None
        try:
            await uc.async_check()
        except Exception:  # noqa: BLE001
            _LOGGER.debug("update re-check failed", exc_info=True)

    async def async_ping(self) -> None:
        await mqtt.async_publish(self.hass, DISCOVERY_PING, "1", 0, False)

    last_ota_url: str | None = None

    def _maybe_local_mirror(self, url: str) -> str:
        """Serve GitHub release binaries over plain LAN HTTP when available."""
        marker = "/releases/download/"
        if marker not in url:
            return url
        fname = url.rsplit("/", 1)[-1]  # firmware-<board>.bin
        if not fname.startswith("firmware-") or not fname.endswith(".bin"):
            return url
        local = Path(__file__).parent / "www" / "firmware" / fname
        if not local.is_file():
            return url
        try:
            from homeassistant.helpers.network import get_url

            base = get_url(self.hass, allow_cloud=False, prefer_internal=True)
            mirrored = f"{base}/home_climate_control_static/firmware/{fname}"
            self.last_ota_url = mirrored
            _LOGGER.warning("OTA mirror engaged: %s -> %s", url, mirrored)
            return mirrored
        except Exception:  # noqa: BLE001
            return url

    async def async_trigger_ota(
        self, node_id: str, url: str
    ) -> dict[str, Any]:
        """Tell device to pull firmware from URL (MQTT + HTTP fallback)."""
        url = self._maybe_local_mirror(url)
        self.last_ota_url = url
        dev = self.devices.get(node_id)
        if not dev:
            return {"ok": False, "error": "unknown device"}
        if not url:
            return {"ok": False, "error": "missing url"}

        # Quiet update-entity / notification thrash while the board reboots.
        try:
            from .update_checker import get_update_checker

            uc = get_update_checker(self.hass)
            if uc is not None:
                uc.mark_install_started()
        except Exception:  # noqa: BLE001
            pass

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
