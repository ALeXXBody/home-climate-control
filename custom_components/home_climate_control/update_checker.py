"""Automatic firmware-update discovery for Home Climate Control.

Periodically queries the GitHub releases of ALeXXBody/home-climate-system,
compares the latest tag against the versions reported by discovered HCS
devices (from their retained discovery JSON), and exposes:
  - availability + changelog (release notes) to the panel
  - a one-time persistent_notification in HA per new version
  - the list of outdated device node_ids for the "Update all" button
"""

from __future__ import annotations

import logging
import time
from datetime import timedelta

from homeassistant.core import HomeAssistant, callback
import aiohttp

from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

RELEASES_API = (
    "https://api.github.com/repos/ALeXXBody/home-climate-system/releases/latest"
)
CHECK_INTERVAL = timedelta(hours=6)
_STORE_VERSION = 1


def version_tuple(v: str | None) -> tuple[int, ...]:
    """'v0.9.2' -> (0, 9, 2); non-numeric parts are dropped."""
    if not v:
        return ()
    parts = []
    for chunk in v.strip().lstrip("vV").split("."):
        digits = ""
        for ch in chunk:
            if ch.isdigit():
                digits += ch
            else:
                break
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def is_newer(candidate: str | None, current: str | None) -> bool:
    return version_tuple(candidate) > version_tuple(current)


class UpdateChecker:
    MIN_CHECK_INTERVAL_S = 600  # never hammer the API more often than this

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.info: dict = {"available": False}
        self._store = Store(hass, _STORE_VERSION, f"{DOMAIN}/update_checker")
        self._notified_tag: str | None = None
        self._token: str | None = None
        self._last_fetch: float = 0.0
        self._unsub = None
        self._unsub_delay = None

    async def async_start(self) -> None:
        data = await self._store.async_load() or {}
        self._notified_tag = data.get("notified_tag")
        self._token = data.get("token")
        # Delayed startup check: retained MQTT discovery needs a moment to
        # populate device versions — an immediate check always saw zero
        # devices and reported "up to date" until the next 6h tick.
        async def _delayed_first(now=None):
            await self.async_check()

        from homeassistant.helpers.event import async_call_later

        self._unsub_delay = async_call_later(self.hass, 15, _delayed_first)
        self._unsub = async_track_time_interval(
            self.hass, self._on_interval, CHECK_INTERVAL
        )

    async def async_set_token(self, token: str | None) -> None:
        """Optional personal access token — raises the API rate limit."""
        self._token = token or None
        await self._store.async_save(
            {"notified_tag": self._notified_tag, "token": self._token}
        )

    async def async_stop(self) -> None:
        if self._unsub_delay:
            self._unsub_delay()
            self._unsub_delay = None
        if self._unsub:
            self._unsub()
            self._unsub = None

    @callback
    async def _on_interval(self, _now) -> None:
        await self.async_check()

    def _outdated_devices(self, latest: str) -> list[dict]:
        from .firmware_manager import get_firmware_manager

        mgr = get_firmware_manager(self.hass)
        out = []
        if not mgr:
            return out
        for node_id, dev in getattr(mgr, "devices", {}).items():
            ver = getattr(dev, "version", None)
            if ver and is_newer(latest, ver):
                out.append(
                    {
                        "node_id": node_id,
                        "version": ver,
                        "board": getattr(dev, "board", ""),
                    }
                )
        return out

    async def async_check(self, force: bool = False) -> dict:
        now = time.monotonic()
        if not force and now - self._last_fetch < self.MIN_CHECK_INTERVAL_S:
            return self.info

        session = aiohttp_client.async_get_clientsession(self.hass)
        headers = {"Accept": "application/vnd.github+json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            resp = await session.get(
                RELEASES_API,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            )
            if resp.status == 403:
                raise RateLimit("GitHub rate limit reached — it will clear "
                                "automatically; optionally add a personal "
                                "access token in the panel")
            if resp.status != 200:
                raise ConnectionError(f"GitHub returned {resp.status}")
            data = await resp.json()
        except RateLimit as err:
            _LOGGER.debug("update check rate-limited")
            self.info = {**self.info, "available": False,
                         "error": str(err), "rate_limited": True}
            return self.info
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Update check failed: %s", err)
            self.info = {**self.info, "available": False, "error": str(err)}
            return self.info
        finally:
            self._last_fetch = time.monotonic()

        tag = data.get("tag_name") or ""
        body = (data.get("body") or "").strip()
        latest = tag.lstrip("vV")

        outdated = self._outdated_devices(latest)
        any_outdated = bool(outdated)
        self.info = {
            "available": any_outdated,
            "latest_tag": tag,
            "latest_version": latest,
            "title": data.get("name") or tag,
            "changelog": body[:4000],
            "url": data.get("html_url"),
            "published_at": data.get("published_at"),
            "outdated_devices": outdated,
            "checked_at": None,  # filled by callers if desired
        }

        # One-time HA notification per new release
        if any_outdated and tag != self._notified_tag:
            from homeassistant.components import persistent_notification

            persistent_notification.async_create(
                self.hass,
                f"Firmware {tag} is available for "
                f"{len(outdated)} device(s): "
                + ", ".join(d["node_id"] for d in outdated)
                + ". Open the Home Climate panel → Firmware to update.",
                title="Home Climate Control — firmware update",
                notification_id=f"{DOMAIN}_fw_{tag}",
            )
            self._notified_tag = tag
            await self._store.async_save(
                {"notified_tag": tag, "token": self._token}
            )

        if not any_outdated and self._notified_tag:
            from homeassistant.components import persistent_notification

            persistent_notification.async_dismiss(
                self.hass, f"{DOMAIN}_fw_{self._notified_tag}"
            )
            self._notified_tag = None

        _LOGGER.info("Firmware check: latest=%s outdated=%d", tag, len(outdated))
        return self.info


class RateLimit(ConnectionError):
    """Raised when GitHub answers 403."""


_ACTIVE: UpdateChecker | None = None


async def async_setup_update_checker(hass: HomeAssistant) -> None:
    global _ACTIVE
    if _ACTIVE is None:
        _ACTIVE = UpdateChecker(hass)
        await _ACTIVE.async_start()


def get_update_checker(hass: HomeAssistant) -> UpdateChecker | None:
    return _ACTIVE
