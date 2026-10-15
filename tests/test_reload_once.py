"""WS handlers reload themselves. A config-entry update listener must not
also reload — that nested unload is what emptied every room after save.
"""
import custom_components.home_climate_control as hcc
from custom_components.home_climate_control.const import INTEGRATION_VERSION
from custom_components.home_climate_control import websocket_api


def test_no_update_listener_that_double_reloads():
    assert not hasattr(hcc, "_async_update_listener")


def test_packaged_version_is_not_the_1_0_0_placeholder():
    # Guard against a stale pin: the version must track the const, and the
    # manifest must agree with const (a mismatch once shipped 1.19.1 code
    # labelled 1.0.0 in HA).
    import json
    from pathlib import Path
    manifest = json.loads(
        (Path(hcc.__file__).parent / "manifest.json").read_text()
    )
    assert INTEGRATION_VERSION == manifest["version"]
    assert websocket_api.INTEGRATION_VERSION != "1.0.0"
