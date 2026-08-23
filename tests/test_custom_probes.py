"""Custom 1-Wire probes: backend parse + HA entity manager."""

import json
from unittest.mock import MagicMock


def test_backend_parses_sensors_snapshot_and_custom_leaf():
    from custom_components.home_climate_control.boiler.hcs_mqtt import HcsMqttBackend

    hass = MagicMock()
    b = HcsMqttBackend(hass, "hcs-aabb", 25.0, 75.0)
    snap = {
        "enabled": True,
        "devices": [
            {
                "addr": "28FF641E0B0000AB",
                "health": "ok",
                "role": "outdoor",
                "temp_c": 4.5,
            },
            {
                "addr": "28FF641E0B0000CD",
                "health": "ok",
                "role": "custom",
                "name": "hall_temp",
                "temp_c": 19.2,
            },
        ],
    }
    b._on_value("sensors", json.dumps(snap))
    assert len(b.sensors_snapshot()) == 2
    assert b.custom_sensors()["hall_temp"] == 19.2

    b._on_value("x/hall_temp", "19.5")
    assert b.custom_sensors()["hall_temp"] == 19.5

    # slash keys other than x/ and sensors still ignored
    b._on_value("set/ch_enable", "on")
    assert b.flame_on is None


def test_backend_sensors_listener_fires():
    from custom_components.home_climate_control.boiler.hcs_mqtt import HcsMqttBackend

    hass = MagicMock()
    b = HcsMqttBackend(hass, "hcs-aabb", 25.0, 75.0)
    hits = []
    b.add_sensors_listener(lambda: hits.append(1))
    b._on_value("x/probe_a", "12.0")
    assert hits == [1]


def test_probe_manager_adds_custom_entities():
    from custom_components.home_climate_control.sensor import ProbeManager

    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "e1"
    entry.data = {"node_id": "hcs-aabb"}
    backend = MagicMock()
    backend.sensors_snapshot.return_value = [
        {"role": "custom", "name": "hall_temp", "temp_c": 18.0, "health": "ok"},
        {"role": "outdoor", "temp_c": 5.0, "health": "ok"},
    ]
    backend.custom_sensors.return_value = {"hall_temp": 18.0}
    backend.add_sensors_listener = MagicMock()
    added = []
    mgr = ProbeManager(hass, entry, backend, lambda ents: added.extend(ents))
    mgr.start()
    assert len(added) == 1
    assert added[0]._probe_name == "hall_temp"
    # second snapshot with same name does not duplicate
    mgr._on_snapshot()
    assert len(added) == 1
