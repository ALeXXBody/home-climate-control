"""Training-data logger — durable per-minute heating telemetry.

The learning features (heat-rate, dead-time, insulation, health) all feed
a future goal: a local model that predicts room behaviour and improves the
control decisions. Such a model is only as good as its training data, so
the integration records what actually happens, one compact row per minute:

    ts · outdoor · CH state · flow setpoint · boiler flame/mod/return
    plus, per zone: temperature, setpoints, preset, demand, window state
    and every learned coefficient (warm rate, dead-time, insulation k)

Storage deliberately lives OUTSIDE custom_components/, in

    <HA config>/home_climate_training/data-YYYY-MM.jsonl

because integration updates replace the whole custom_components folder.
The config root survives them untouched, so history accumulates across
versions — exactly what a training corpus needs. Files are newline-
delimited JSON: trivially appendable, streamable into pandas/pytorch, and
one file per month keeps sizes manageable.

Reliability rules:
- rows are buffered and flushed every ~5 min (or 500 rows) asynchronously;
- an HA stop triggers a final flush;
- retention prunes month-files older than KEEP_MONTHS;
- every failure is swallowed and logged — logging must never disturb heat.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

DIR_NAME = "home_climate_training"
FLUSH_INTERVAL_S = 300
FLUSH_ROWS = 500
KEEP_MONTHS = 13


def _month_key(value: Any = None) -> str:
    """Month bucket ('YYYY-MM') from an ISO ts string or unix seconds."""
    if value is None:
        return datetime.now(timezone.utc).strftime("%Y-%m")
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return datetime.now(timezone.utc).strftime("%Y-%m")
        return dt.strftime("%Y-%m")
    return datetime.fromtimestamp(value, tz=timezone.utc).strftime("%Y-%m")


class TrainingDataLogger:
    """Buffers control-loop snapshots and appends them to monthly JSONL."""

    def __init__(self, hass: HomeAssistant | None, *, enabled: bool = True) -> None:
        self.hass = hass
        self.enabled = enabled
        self._buf: list[dict[str, Any]] = []
        self._last_flush = time.time()
        self.rows_total = 0
        self.last_row_ts: str | None = None
        self._pruned_month: str | None = None
        self._dir: Path | None = None
        if hass is not None:
            try:
                self._dir = Path(hass.config.path(DIR_NAME))
            except Exception:  # noqa: BLE001
                self._dir = None

    # ------------------------------------------------------------------ feed
    def feed(self, row: dict[str, Any]) -> None:
        """Queue one snapshot; flushes happen in the background."""
        if not self.enabled or self._dir is None:
            return
        ts_iso = row.get("ts") or datetime.now(timezone.utc).isoformat(timespec="seconds")
        row = {**row, "ts": ts_iso}
        self._buf.append(row)
        self.last_row_ts = ts_iso
        if len(self._buf) >= FLUSH_ROWS or (
            time.time() - self._last_flush >= FLUSH_INTERVAL_S
        ):
            self.schedule_flush()

    def schedule_flush(self) -> None:
        if not self._buf:
            return
        rows = self._buf
        self._buf = []
        self._last_flush = time.time()
        if self.hass is not None and hasattr(self.hass, "async_create_task"):
            self.hass.async_create_task(self._async_write(rows))
        else:
            import asyncio

            try:
                asyncio.get_running_loop()
            except RuntimeError:
                asyncio.run(self._async_write(rows))
            else:
                asyncio.ensure_future(self._async_write(rows))

    # ------------------------------------------------------------------ disk
    async def _async_write(self, rows: list[dict[str, Any]]) -> None:
        try:
            assert self._dir is not None
            await self.hass.async_add_executor_job(
                self._sync_write, rows
            )
        except Exception:  # noqa: BLE001 - never break heating over logs
            _LOGGER.warning("Training-log flush failed", exc_info=True)
            # keep rows rather than lose them: requeue at the front
            self._buf = rows + self._buf
            if len(self._buf) > 5000:  # absolute safety cap
                del self._buf[5000:]

    def _sync_write(self, rows: list[dict[str, Any]]) -> None:
        assert self._dir is not None
        self._dir.mkdir(parents=True, exist_ok=True)
        by_month: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            by_month.setdefault(_month_key(r["ts"]), []).append(r)
        for month, mrows in sorted(by_month.items()):
            path = self._dir / f"data-{month}.jsonl"
            with open(path, "a", encoding="utf-8") as fh:
                for r in mrows:
                    fh.write(json.dumps(r, separators=(",", ":")) + "\n")
            self.rows_total += len(mrows)
            _LOGGER.debug("Training log: %d row(s) -> %s", len(mrows), path.name)
        self._write_meta()
        self._prune_old_months()

    def _write_meta(self) -> None:
        try:
            assert self._dir is not None
            (self._dir / "meta.json").write_text(
                json.dumps({"rows_total": self.rows_total}),
                encoding="utf-8",
            )
        except Exception:  # noqa: BLE001
            pass

    def _load_meta(self) -> None:
        try:
            assert self._dir is not None
            meta = json.loads((self._dir / "meta.json").read_text(encoding="utf-8"))
            self.rows_total = int(meta.get("rows_total", 0))
        except Exception:  # noqa: BLE001
            self.rows_total = 0

    def _prune_old_months(self) -> None:
        this_month = _month_key()
        if self._pruned_month == this_month:
            return
        self._pruned_month = this_month
        try:
            assert self._dir is not None
            cutoff_y, cutoff_m = (int(x) for x in this_month.split("-"))
            cutoff_idx = cutoff_y * 12 + cutoff_m - KEEP_MONTHS
            for f in self._dir.glob("data-*.jsonl"):
                parts = f.stem.split("-")
                if len(parts) < 3:
                    continue
                try:
                    y, m = int(parts[1]), int(parts[2])
                except ValueError:
                    continue
                if y * 12 + m < cutoff_idx:
                    os.remove(f)
                    _LOGGER.info("Training log: pruned %s", f.name)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("retention prune failed", exc_info=True)

    # ------------------------------------------------------------------ init
    def async_start(self) -> None:
        self._load_meta()

    async def async_stop(self) -> None:
        if not self._buf:
            return
        rows = self._buf
        self._buf = []
        await self._async_write(rows)

    # --------------------------------------------------------------- output
    def stats(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "rows_total": self.rows_total,
            "rows_buffered": len(self._buf),
            "last_row_ts": self.last_row_ts,
            "directory": str(self._dir) if self._dir else None,
            "current_file": f"data-{_month_key()}.jsonl",
        }
