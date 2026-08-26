"""Sidebar panel registration for Home Climate."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from aiohttp import web
from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN,
    PANEL_ICON,
    PANEL_JS,
    PANEL_STATIC_URL,
    PANEL_TITLE,
    PANEL_URL_PATH,
    PANEL_WEBCOMPONENT,
)

_LOGGER = logging.getLogger(__name__)

_PANEL_REGISTERED = f"{DOMAIN}_panel_registered"
_STATIC_REGISTERED = f"{DOMAIN}_static_registered"


async def async_register_panel(hass: HomeAssistant) -> None:
    """Serve frontend assets and add Home Climate to the sidebar."""
    if hass.data.get(_PANEL_REGISTERED):
        return

    www_dir = Path(__file__).parent / "www"
    if not www_dir.is_dir():
        _LOGGER.error("Panel www directory missing: %s", www_dir)
        return

    if not hass.data.get(_STATIC_REGISTERED):
        # Exact-path route FIRST: serves the panel script with hard no-store
        # headers so reverse proxies/CDNs never poison it (heuristic caching
        # of unlabelled responses froze some installs on old builds).
        async def _serve_panel_js(request):
            f = www_dir / PANEL_JS
            if not f.is_file():
                return web.Response(status=404)
            resp = web.FileResponse(f)
            resp.headers["Cache-Control"] = "no-store, must-revalidate"
            resp.headers["Pragma"] = "no-cache"
            return resp

        hass.http.app.router.add_get(
            f"{PANEL_STATIC_URL}/{PANEL_JS}", _serve_panel_js
        )
        await hass.http.async_register_static_paths(
            [StaticPathConfig(PANEL_STATIC_URL, str(www_dir), cache_headers=False)]
        )
        hass.data[_STATIC_REGISTERED] = True

    version = "0.2.0"
    manifest = Path(__file__).parent / "manifest.json"
    if manifest.is_file():
        try:
            version = json.loads(manifest.read_text(encoding="utf-8")).get(
                "version", version
            )
        except (OSError, json.JSONDecodeError):
            pass

    module_url = f"{PANEL_STATIC_URL}/{PANEL_JS}?v={version}"

    await panel_custom.async_register_panel(
        hass,
        webcomponent_name=PANEL_WEBCOMPONENT,
        frontend_url_path=PANEL_URL_PATH,
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        module_url=module_url,
        embed_iframe=False,
        require_admin=False,
        config={"domain": DOMAIN},
    )
    hass.data[_PANEL_REGISTERED] = True
    _LOGGER.info("Registered sidebar panel at /%s", PANEL_URL_PATH)


async def async_unregister_panel(hass: HomeAssistant) -> None:
    """Remove sidebar panel when last config entry unloads."""
    if not hass.data.get(_PANEL_REGISTERED):
        return
    frontend.async_remove_panel(hass, PANEL_URL_PATH)
    hass.data[_PANEL_REGISTERED] = False
    _LOGGER.info("Removed sidebar panel /%s", PANEL_URL_PATH)
