"""Shared HA Store persistence helper (dedupes the async-save scaffolding)."""

from __future__ import annotations

import logging
from typing import Any


def schedule_store_save(
    hass: Any, store: Any, payload: dict, tag: str, logger: logging.Logger
) -> None:
    """Persist *payload* via *store* off the event loop (best-effort).

    Each learning module (setback / deadtime / insulation) used to carry the
    same async_save + scheduling dance; that is now a single implementation.
    """

    async def _save() -> None:
        try:
            await store.async_save(payload)
        except Exception:  # noqa: BLE001
            logger.debug("%s persist failed", tag, exc_info=True)

    if hass is not None and hasattr(hass, "async_create_task"):
        hass.async_create_task(_save())
        return

    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(_save())
    else:
        asyncio.ensure_future(_save())
