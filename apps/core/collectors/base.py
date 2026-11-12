from __future__ import annotations

import time
from typing import Any


class Collector:
    """Base collector adapter."""

    collector_type = "generic"

    def __init__(self, collector_id: str, interval_seconds: float, enabled: bool = True):
        self.collector_id = collector_id
        self.interval_seconds = max(5.0, float(interval_seconds))
        self.enabled = enabled
        self._last_run_at = 0.0
        self._next_run_at = 0.0
        self._last_duration_ms = None
        self._last_error = None
        self._last_data = None
        self._run_count = 0

    def collect(self) -> dict[str, Any]:
        raise NotImplementedError

    def due(self, now: float | None = None) -> bool:
        if not self.enabled:
            return False
        current = now if now is not None else time.time()
        return current >= self._next_run_at

    def run(self, now: float | None = None) -> dict[str, Any]:
        current = now if now is not None else time.time()
        started = time.perf_counter()
        try:
            payload = self.collect()
            if not isinstance(payload, dict):
                raise TypeError(f"collector {self.collector_id} returned non-object payload")
            self._last_data = payload
            self._last_error = None
            status = "ok"
        except Exception as exc:
            self._last_error = str(exc)
            status = "error"
            payload = self._last_data if isinstance(self._last_data, dict) else None

        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        self._last_run_at = current
        self._next_run_at = current + self.interval_seconds
        self._last_duration_ms = duration_ms
        self._run_count += 1
        return self.snapshot(status=status, include_data=True, data_override=payload)

    def snapshot(self, status: str | None = None, include_data: bool = False, data_override=None) -> dict[str, Any]:
        if status is None:
            status = "error" if self._last_error else ("ok" if self._last_data is not None else "idle")
        item = {
            "id": self.collector_id,
            "type": self.collector_type,
            "enabled": self.enabled,
            "intervalSeconds": int(self.interval_seconds),
            "status": status,
            "runCount": self._run_count,
            "lastRunAt": _iso_utc(self._last_run_at),
            "nextRunAt": _iso_utc(self._next_run_at),
            "lastDurationMs": self._last_duration_ms,
            "lastError": self._last_error,
        }
        summary = self.summarize(self._last_data if data_override is None else data_override)
        if summary:
            item.update(summary)
        if include_data:
            item["data"] = data_override if data_override is not None else self._last_data
        return item

    def summarize(self, data: dict[str, Any] | None) -> dict[str, Any]:
        return {}


def _iso_utc(epoch: float) -> str | None:
    if not epoch:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))
