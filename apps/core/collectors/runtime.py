from __future__ import annotations

import logging
import threading
import time
from typing import Any

from collectors.base import Collector

logger = logging.getLogger("hcc.collectors")


class CollectorRuntime:
    def __init__(self, collectors: list[Collector], tick_seconds: float = 5.0):
        self._collectors = collectors
        self._tick_seconds = max(1.0, float(tick_seconds))
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._started_at = None

    @property
    def enabled(self) -> bool:
        return any(collector.enabled for collector in self._collectors)

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        if not self.enabled:
            logger.info("collector runtime has no enabled collectors; not starting background thread")
            return
        self._started_at = time.time()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="hcc-collectors", daemon=True)
        self._thread.start()
        logger.info("collector runtime started (%s collectors)", len(self._collectors))

    def stop(self):
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def run_due(self, now: float | None = None) -> list[dict[str, Any]]:
        current = now if now is not None else time.time()
        results = []
        for collector in self._collectors:
            if not collector.due(current):
                continue
            try:
                results.append(collector.run(current))
            except Exception as exc:
                logger.exception("collector %s failed: %s", collector.collector_id, exc)
        return results

    def index(self) -> dict[str, Any]:
        with self._lock:
            collectors = [collector.snapshot(include_data=False) for collector in self._collectors]
        return {
            "enabled": self.enabled,
            "startedAt": _iso_utc(self._started_at),
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "collectorCount": len(collectors),
            "activeCount": sum(1 for item in collectors if item.get("enabled")),
            "collectors": collectors,
        }

    def detail(self, collector_id: str, include_data: bool = True) -> dict[str, Any] | None:
        for collector in self._collectors:
            if collector.collector_id != collector_id:
                continue
            return collector.snapshot(include_data=include_data)
        return None

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.run_due()
            except Exception:
                logger.exception("collector runtime tick failed")
            self._stop.wait(self._tick_seconds)


def _iso_utc(epoch: float | None) -> str | None:
    if not epoch:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))
