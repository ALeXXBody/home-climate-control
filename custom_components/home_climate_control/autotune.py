"""Self-tuning heating curve coefficient.

Mission: burn minimum gas while rooms hold their setpoints.

The curve coefficient (CURVE_COEFF) decides how aggressively flow
temperature rises as it gets colder outside. Too low -> rooms never quite
reach setpoint in cold weather. Too high -> overshoot, wasted gas, and
valves throttling. This module watches the achieved comfort over time and
nudges the coefficient in small steps:

  * sustained "rooms slightly cold"  -> coefficient up
  * sustained "rooms slightly hot"   -> coefficient down (overshoot = gas)
  * inside deadband                  -> do nothing

Moves are small, rare (>=1 h apart - buildings react slowly) and clamped
to [CURVE_COEFF_MIN, CURVE_COEFF_MAX]. The learned value survives restarts
via the HA Store.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.helpers.storage import Store

from .const import CURVE_COEFF_MAX, CURVE_COEFF_MIN

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = "home_climate_control_autotune"
STORAGE_VERSION = 1

# Learning dynamics - deliberately slow and conservative.
EVALUATE_EVERY_S = 20 * 60        # consider a move at most every 20 min
COOLDOWN_AFTER_MOVE_S = 60 * 60   # thermal lag: wait an hour after a move
EMA_WINDOW_S = 30 * 60            # comfort-error smoothing horizon
DEADBAND_C = 0.2                  # degC; |mean error| under this = fine
STEP_MIN = 0.01
STEP_MAX = 0.10


class CurveAutoTuner:
    """Adjusts CentralController.curve_coeff from observed room comfort."""

    def __init__(
        self,
        hass,
        initial_coeff: float,
        *,
        enabled: bool = True,
        coeff_min: float = CURVE_COEFF_MIN,
        coeff_max: float = CURVE_COEFF_MAX,
    ) -> None:
        self.hass = hass
        self.enabled = enabled
        self.coeff_min = coeff_min
        self.coeff_max = coeff_max
        self.coeff = float(initial_coeff)
        self.adjustments = 0
        self.last_action = "listening"
        self.mean_error: float | None = None

        self._ema = 0.0
        self._last_sample_mono: float | None = None
        self._next_eval_mono = 0.0
        self._cooldown_until_mono = 0.0
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY) if hass else None

    # ------------------------------------------------------------------ I/O
    async def async_load(self) -> None:
        """Restore the learned coefficient across restarts."""
        if self._store is None:
            return
        try:
            data = await self._store.async_load() or {}
        except Exception:  # noqa: BLE001
            data = {}
        saved = data.get("coeff")
        if isinstance(saved, (int, float)):
            self.coeff = min(self.coeff_max, max(self.coeff_min, float(saved)))
            _LOGGER.info("Auto-tune restored curve coefficient %.3f", self.coeff)
        self.adjustments = int(data.get("adjustments", 0) or 0)

    def _persist(self) -> None:
        if self._store is None:
            return

        async def _save() -> None:
            try:
                await self._store.async_save(
                    {"coeff": self.coeff, "adjustments": self.adjustments}
                )
            except Exception:  # noqa: BLE001
                _LOGGER.debug("autotune persist failed", exc_info=True)

        task_factory = (
            self.hass.async_create_task
            if self.hass is not None and hasattr(self.hass, "async_create_task")
            else None
        )
        if task_factory is not None:
            task_factory(_save())
        else:
            # Direct/test usage without a running hass.
            import asyncio

            try:
                asyncio.get_running_loop()
            except RuntimeError:
                asyncio.run(_save())
            else:  # inside a loop: fire-and-forget
                asyncio.ensure_future(_save())

    # --------------------------------------------------------------- learning
    def observe(
        self, mean_error_c: float | None, heating_active: bool, now: float | None = None
    ) -> None:
        """Feed one control tick's aggregate room error (target - actual)."""
        now = time.monotonic() if now is None else now
        if not heating_active or mean_error_c is None:
            # No signal while idle/window-open/faulted: let the EMA decay
            # toward zero so stale errors don't drive later decisions.
            if self._last_sample_mono is not None:
                self._ema *= 0.5
                self._last_sample_mono = now
            return

        dt = (
            0.0
            if self._last_sample_mono is None
            else min(600.0, now - self._last_sample_mono)
        )
        alpha = min(1.0, dt / EMA_WINDOW_S) if dt > 0 else 0.0
        self._ema += alpha * (mean_error_c - self._ema)
        self._last_sample_mono = now
        self.mean_error = mean_error_c

    def step(self, now: float | None = None) -> float | None:
        """Maybe adjust the coefficient. Returns new coeff or None."""
        if not self.enabled:
            return None
        now = time.monotonic() if now is None else now
        if now < self._next_eval_mono or now < self._cooldown_until_mono:
            return None
        self._next_eval_mono = now + EVALUATE_EVERY_S

        err = self._ema
        if abs(err) < DEADBAND_C:
            self.last_action = "comfort ok - holding"
            return None

        direction = 1.0 if err > 0 else -1.0  # cold -> more heat capability
        magnitude = min(STEP_MAX, max(STEP_MIN, 0.05 * abs(err)))
        new_coeff = min(
            self.coeff_max, max(self.coeff_min, self.coeff + direction * magnitude)
        )
        if abs(new_coeff - self.coeff) < 1e-6:
            self.last_action = "at limit - holding"
            return None

        self.coeff = round(new_coeff, 3)
        self.adjustments += 1
        self._cooldown_until_mono = now + COOLDOWN_AFTER_MOVE_S
        self.last_action = (
            f"{'raised' if direction > 0 else 'lowered'} to "
            f"{self.coeff:.2f} (rooms {'cold' if direction > 0 else 'hot'} by "
            f"{abs(err):.2f} C)"
        )
        _LOGGER.info("Curve auto-tune %s", self.last_action)
        self._persist()
        return self.coeff

    # ------------------------------------------------------------ introspection
    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "learned_coeff": self.coeff,
            "mean_error": (
                round(self.mean_error, 3) if self.mean_error is not None else None
            ),
            "adjustments": self.adjustments,
            "last_action": self.last_action,
        }
