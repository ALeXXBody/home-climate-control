"""In-process demo boiler gateway (no MQTT / no hardware).

Simulates outdoor temperature, boiler flow/return/modulation/flame, and
simple room thermal dynamics so the sidebar app and climate entities can
be tested without hardware.
"""

from __future__ import annotations

import logging
import math
import time
from typing import Any

from .base import BoilerBackend

_LOGGER = logging.getLogger(__name__)


class DemoBoilerBackend(BoilerBackend):
    """Virtual boiler + rooms for development and UI testing."""

    def __init__(
        self,
        min_flow: float,
        max_flow: float,
        *,
        outdoor: float = 5.0,
        rooms: dict[str, float] | None = None,
    ) -> None:
        self._min_flow = min_flow
        self._max_flow = max_flow
        self._outdoor = outdoor
        self._flow_temp = outdoor + 15.0
        self._return_temp = outdoor + 10.0
        self._modulation = 0.0
        self._flame = False
        self._ch_enabled = False
        self._ch_active = False
        self._commanded_setpoint: float | None = None
        self._max_mod = 100.0
        self._rooms: dict[str, float] = dict(rooms or {})
        self._last_tick = time.monotonic()
        self._started = False

    # --- lifecycle -----------------------------------------------------------
    async def async_start(self) -> None:
        self._started = True
        self._last_tick = time.monotonic()
        _LOGGER.info(
            "Demo boiler started (outdoor=%.1f °C, rooms=%s)",
            self._outdoor,
            list(self._rooms),
        )

    async def async_stop(self) -> None:
        self._started = False
        self._flame = False
        self._ch_active = False

    # --- commands ------------------------------------------------------------
    async def async_set_ch_enabled(self, enabled: bool) -> None:
        self._ch_enabled = enabled
        if not enabled:
            self._flame = False
            self._ch_active = False
            self._modulation = 0.0

    async def async_set_flow_setpoint(self, temp: float) -> None:
        temp = max(self._min_flow, min(self._max_flow, temp))
        temp = round(temp * 2) / 2.0
        self._commanded_setpoint = temp

    async def async_set_max_modulation(self, percent: float) -> None:
        self._max_mod = max(0.0, min(100.0, float(percent)))

    # --- room API (demo-only) ------------------------------------------------
    def ensure_room(self, name: str, initial: float = 18.0) -> None:
        if name not in self._rooms:
            self._rooms[name] = initial

    def get_room_temp(self, name: str) -> float | None:
        return self._rooms.get(name)

    def set_room_temp(self, name: str, temp: float) -> None:
        self._rooms[name] = temp

    def simulate_step(self, zones: list) -> None:
        """Advance boiler + room physics; call once per control loop."""
        now = time.monotonic()
        dt = max(1.0, min(300.0, now - self._last_tick))
        self._last_tick = now

        target = self._commanded_setpoint
        heating = bool(self._ch_enabled and target is not None and target > self._outdoor + 5)

        if heating:
            self._ch_active = True
            # Flow water lags toward commanded setpoint.
            assert target is not None
            alpha = 1.0 - math.exp(-dt / 45.0)
            self._flow_temp += (target - self._flow_temp) * alpha
            # Modulation rises with gap between flow and outdoor / load.
            load = max(0.0, (target - self._outdoor) / max(1.0, self._max_flow - self._outdoor))
            self._modulation = min(self._max_mod, 15.0 + load * 70.0)
            self._flame = self._modulation > 5.0
            self._return_temp = self._flow_temp - (8.0 + self._modulation * 0.05)
        else:
            self._ch_active = False
            self._flame = False
            self._modulation = 0.0
            cool = 1.0 - math.exp(-dt / 120.0)
            idle = self._outdoor + 8.0
            self._flow_temp += (idle - self._flow_temp) * cool
            self._return_temp = self._flow_temp - 2.0

        # Rooms: heat when CH on and zone wants heat; otherwise drift to outdoor-ish.
        for zone in zones:
            name = getattr(zone, "name", None) or getattr(zone, "_attr_name", None)
            if not name:
                continue
            if name not in self._rooms:
                self._rooms[name] = 18.0
            room = self._rooms[name]
            wants = False
            try:
                wants = bool(zone.wants_heat() and not zone.paused())
            except Exception:  # noqa: BLE001
                wants = False

            if heating and wants and self._flame:
                # Effective emitter temp drives room up slowly.
                drive = min(self._flow_temp, (self._commanded_setpoint or self._flow_temp))
                # ~0.4–1.2 °C/h depending on flow
                rate = 0.15 + max(0.0, (drive - 30.0) / 80.0)  # °C per minute-ish scaled
                room += rate * (dt / 60.0)
            else:
                # Cool toward outdoor + 12 °C (building fabric)
                equilibrium = self._outdoor + 12.0
                room += (equilibrium - room) * (1.0 - math.exp(-dt / 900.0))

            self._rooms[name] = round(max(5.0, min(35.0, room)), 2)

        # Gentle outdoor drift (day/night-ish sine over ~24 min for visible demo)
        phase = (now % 1440) / 1440.0 * 2 * math.pi
        self._outdoor = 5.0 + 3.0 * math.sin(phase)

    # --- telemetry -----------------------------------------------------------
    @property
    def outdoor_temp(self) -> float | None:
        return round(self._outdoor, 1)

    @property
    def outdoor_age_s(self) -> float | None:
        return 0.0  # always fresh (simulated)

    @property
    def flow_temp(self) -> float | None:
        return round(self._flow_temp, 1)

    @property
    def return_temp(self) -> float | None:
        return round(self._return_temp, 1)

    @property
    def modulation_level(self) -> float | None:
        return round(self._modulation, 1)

    @property
    def flame_on(self) -> bool | None:
        return self._flame

    @property
    def ch_active(self) -> bool | None:
        return self._ch_active

    def diagnostics(self) -> dict[str, Any]:
        data = super().diagnostics()
        data.update(
            {
                "backend": "demo",
                "commanded_setpoint": self._commanded_setpoint,
                "rooms": dict(self._rooms),
                "demo": True,
            }
        )
        return data
