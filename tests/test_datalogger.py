"""Training-data logger: buffering, JSONL flush, rotation, retention."""

import asyncio
import json
from pathlib import Path

import pytest

from custom_components.home_climate_control.datalogger import (
    FLUSH_ROWS,
    TrainingDataLogger,
)


class _FakeConfig:
    def __init__(self, root: Path):
        self._root = root

    def path(self, rel: str) -> str:
        return str(self._root / rel)


class _FakeHass:
    def __init__(self, root: Path):
        self.config = _FakeConfig(root)
        self.tasks = []

    def async_create_task(self, coro):
        self.tasks.append(coro)
        return coro

    async def async_add_executor_job(self, func, *args):
        return func(*args)


@pytest.fixture
def root(tmp_path):
    return tmp_path


def _row(ts_iso="2026-08-24T19:00:00+00:00", temp=20.4):
    return {
        "ts": ts_iso,
        "outdoor": 11.0,
        "ch_on": True,
        "flow_setpoint": 44.0,
        "zones": [{"name": "Living", "temp": temp}],
    }


def test_rows_buffered_then_flushed_as_jsonl(root):
    hass = _FakeHass(root)
    log = TrainingDataLogger(hass)
    log.async_start()
    for i in range(FLUSH_ROWS + 1):  # crosses the row threshold
        log.feed(_row())
    # threshold flush scheduled into the fake task queue; the extra row
    # stays buffered for the next round.
    assert len(log._buf) == 1
    assert len(hass.tasks) >= 1


def test_manual_flush_writes_and_counts(root):
    hass = _FakeHass(root)
    log = TrainingDataLogger(hass)
    log.async_start()
    log.feed(_row("2026-08-24T19:00:00+00:00"))
    log.feed(_row("2026-08-24T19:01:00+00:00"))
    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        log._async_write(log._buf)
    )
    log._buf.clear()
    f = Path(hass.config.path("home_climate_training")) / "data-2026-08.jsonl"
    lines = [json.loads(x) for x in f.read_text().splitlines()]
    assert len(lines) == 2
    assert lines[0]["zones"][0]["name"] == "Living"
    assert log.rows_total == 2
    meta = json.loads((f.parent / "meta.json").read_text())
    assert meta["rows_total"] == 2


def test_monthly_rotation_across_files(root):
    hass = _FakeHass(root)
    log = TrainingDataLogger(hass)
    log.feed(_row("2026-07-31T23:59:00+00:00"))
    log.feed(_row("2026-08-01T00:01:00+00:00"))
    import asyncio

    asyncio.run(log._async_write(log._buf))
    d = Path(hass.config.path("home_climate_training"))
    assert (d / "data-2026-07.jsonl").exists()
    assert (d / "data-2026-08.jsonl").exists()


def test_retention_prunes_old_months(root):
    hass = _FakeHass(root)
    d = Path(hass.config.path("home_climate_training"))
    d.mkdir(parents=True)
    (d / "data-2024-01.jsonl").write_text("{}\n")
    (d / "data-2026-08.jsonl").write_text("{}\n")
    log = TrainingDataLogger(hass)
    log._dir = d
    log._pruned_month = None
    log._prune_old_months()
    assert not (d / "data-2024-01.jsonl").exists()
    assert (d / "data-2026-08.jsonl").exists()


def test_stats_shape(root):
    hass = _FakeHass(root)
    log = TrainingDataLogger(hass)
    log.async_start()
    st = log.stats()
    assert st["enabled"] is True
    assert "home_climate_training" in st["directory"]
    assert st["current_file"].startswith("data-")
