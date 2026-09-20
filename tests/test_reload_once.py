"""WS handlers reload themselves. A config-entry update listener must not
also reload — that nested unload is what emptied every room after save.
"""
import custom_components.home_climate_control as hcc


def test_no_update_listener_that_double_reloads():
    assert not hasattr(hcc, "_async_update_listener")
