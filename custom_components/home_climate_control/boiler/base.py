"""Boiler backend abstraction.

A backend knows how to command the boiler (CH enable, flow setpoint, max
modulation) and how to expose telemetry (flow temp, return temp, modulation,
flame, outdoor temp). Backends are push-based: they keep their attributes
updated from their transport and the central controller reads them.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BoilerBackend(ABC):
    """Interface every boiler driver must implement."""

    @abstractmethod
    async def async_start(self) -> None:
        """Subscribe/connect to the transport."""

    @abstractmethod
    async def async_stop(self) -> None:
        """Unsubscribe/disconnect."""

    @abstractmethod
    async def async_set_ch_enabled(self, enabled: bool) -> None:
        """Enable/disable central heating."""

    @abstractmethod
    async def async_set_flow_setpoint(self, temp: float) -> None:
        """Command the control setpoint (TSet), clamped by config limits."""

    @abstractmethod
    async def async_set_max_modulation(self, percent: float) -> None:
        """Limit relative modulation level (MM)."""

    # --- telemetry -----------------------------------------------------------
    @property
    @abstractmethod
    def outdoor_temp(self) -> float | None:
        """Outdoor temperature reported by the gateway/boiler (°C)."""

    @property
    @abstractmethod
    def flow_temp(self) -> float | None: ...

    @property
    @abstractmethod
    def return_temp(self) -> float | None: ...

    @property
    @abstractmethod
    def modulation_level(self) -> float | None: ...

    @property
    @abstractmethod
    def flame_on(self) -> bool | None: ...

    @property
    @abstractmethod
    def ch_active(self) -> bool | None: ...

    @property
    def connected(self) -> bool:
        """Backends without a link notion (demo, plain switch) are always
        considered connected."""
        return True

    @property
    def outdoor_age_s(self) -> float | None:
        """Seconds since outdoor_temp was last updated, or None if unknown.

        Controllers use this to fall back to a HA sensor when the boiler
        outdoor reading goes stale. Backends that always have a fresh value
        (demo) return 0.0.
        """
        return None

    def diagnostics(self) -> dict[str, Any]:
        return {
            "outdoor_temp": self.outdoor_temp,
            "flow_temp": self.flow_temp,
            "return_temp": self.return_temp,
            "modulation_level": self.modulation_level,
            "flame_on": self.flame_on,
            "ch_active": self.ch_active,
        }
