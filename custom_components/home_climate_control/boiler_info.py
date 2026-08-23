"""Per-entry boiler identity: detected manufacturer (from MemberID) plus a
manually selected make/model, shown with a picture on the panel overview."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .boilers import make_for_member, models_for_make

_LOGGER = logging.getLogger(__name__)

_STORE_VERSION = 1
_STATIC_DIR = Path(__file__).parent / "www" / "boilers"
_STATIC_URL = "/home_climate_control_static/boilers"
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".svg", ".webp")


def _slug(s: str) -> str:
    return s.lower().strip().replace(" ", "_").replace("/", "_")


def image_url_for(make: str | None, model: str | None) -> str | None:
    """Resolve the picture for make/model against bundled static files."""
    candidates = []
    if make:
        short = _slug(make.split("/")[0])  # "Remeha / De Dietrich" -> remeha
        if model:
            candidates.append(f"{short}_{_slug(model)}")
        candidates.append(short)
    for cand in candidates:
        for ext in _IMAGE_EXTS:
            f = _STATIC_DIR / f"{cand}{ext}"
            if f.is_file():
                return f"{_STATIC_URL}/{cand}{ext}"
    generic = _STATIC_DIR / "generic.svg"
    if generic.is_file():
        return f"{_STATIC_URL}/generic.svg"
    return None


class BoilerInfo:
    """Holds detected + selected boiler identity for one config entry."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self.hass = hass
        self.entry_id = entry_id
        self.member_id: int | None = None
        self.make: str | None = None       # manual selection wins
        self.model: str | None = None
        self._store = Store(hass, _STORE_VERSION, f"{DOMAIN}/boiler_info_{entry_id}")
        self._unsub = None

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self.member_id = data.get("member_id")
        self.make = data.get("make")
        self.model = data.get("model")

        @callback
        def on_member(msg) -> None:
            try:
                mid = int(str(msg.payload).strip())
            except ValueError:
                return
            changed = mid != self.member_id
            self.member_id = mid
            # auto-fill the make when we have no selection yet or ID changed
            detected = make_for_member(mid)
            if detected and changed and not self.make:
                self.make = detected
                self.model = models_for_make(detected)[0] if models_for_make(detected) else None
                await self.async_save()
            if changed:
                _LOGGER.info("Boiler memberID %s detected (%s)", mid, detected)

        self._unsub = await mqtt.async_subscribe(
            self.hass, "hcs/+/boiler_member", on_member, 0
        )

    async def async_unload(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None

    async def async_save(self) -> None:
        await self._store.async_save(
            {
                "member_id": self.member_id,
                "make": self.make,
                "model": self.model,
            }
        )

    async def async_set_selection(self, make: str | None, model: str | None) -> None:
        self.make = make or None
        self.model = model or None
        await self.async_save()

    def as_dict(self) -> dict:
        return {
            "member_id": self.member_id,
            "detected_make": make_for_member(self.member_id),
            "make": self.make,
            "model": self.model,
            "image": image_url_for(self.make, self.model),
            "models_available": models_for_make(self.make),
        }


_ACTIVE: dict[str, BoilerInfo] = {}


async def async_setup_boiler_info(hass: HomeAssistant, entry_id: str) -> BoilerInfo:
    info = _ACTIVE.get(entry_id)
    if info is None:
        info = BoilerInfo(hass, entry_id)
        _ACTIVE[entry_id] = info
        await info.async_load()
    return info


def get_boiler_info(hass: HomeAssistant) -> BoilerInfo | None:
    entry_id = next(iter(hass.data.get(DOMAIN, {})), None)
    return _ACTIVE.get(entry_id)
