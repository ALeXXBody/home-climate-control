"""Import-smoke test: every integration module must import cleanly.

Catches module-level errors (bad decorators, typos, missing names) that
function-level tests skip because they never import the real module.
"""

from __future__ import annotations

import importlib
import pkgutil

import pytest


MODULES = [
    "boilers",
    "boiler_info",
    "config_flow",
    "const",
    "firmware_manager",
    "panel",
    "pid",
    "heating_curve",
    "sensor",
    "update_checker",
    "websocket_api",
    "climate",
    "central",
]


@pytest.mark.parametrize("name", MODULES)
def test_module_imports(name: str) -> None:
    importlib.import_module(f"custom_components.home_climate_control.{name}")


def test_package_imports() -> None:
    import custom_components.home_climate_control as pkg  # noqa: F401

    for m in pkgutil.iter_modules(pkg.__path__):
        if not m.ispkg:
            importlib.import_module(f"{pkg.__name__}.{m.name}")
