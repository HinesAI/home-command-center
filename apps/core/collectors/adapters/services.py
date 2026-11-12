from __future__ import annotations

from typing import Any, Callable

import integrations
from collectors.base import Collector


class ServiceCollector(Collector):
    collector_type = "service"

    def __init__(
        self,
        collector_id: str,
        interval_seconds: float,
        service_name: str,
        fetch_fn: Callable[[], dict[str, Any]],
        enabled: bool = True,
    ):
        super().__init__(collector_id, interval_seconds, enabled=enabled)
        self.service_name = service_name
        self._fetch_fn = fetch_fn

    def collect(self) -> dict[str, Any]:
        payload = self._fetch_fn()
        if not isinstance(payload, dict):
            raise TypeError(f"service collector {self.collector_id} returned non-object payload")
        return {"service": self.service_name, "payload": payload}

    def summarize(self, data: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(data, dict):
            return {"recordCount": 0}
        payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
        if self.service_name == "homeassistant-security":
            totals = payload.get("totals") if isinstance(payload.get("totals"), dict) else {}
            return {
                "recordCount": int(totals.get("serviceCount") or 0),
                "onlineCount": int(totals.get("onlineCount") or 0),
            }
        if self.service_name == "weather":
            return {"recordCount": 1 if payload.get("current") else 0}
        if self.service_name == "network":
            return {"recordCount": 1 if payload.get("speedtest") or payload.get("gateway") else 0}
        if self.service_name == "climate":
            totals = payload.get("totals") if isinstance(payload.get("totals"), dict) else {}
            return {"recordCount": int(totals.get("thermostatCount") or 0)}
        return {"recordCount": 1 if payload else 0}


def climate_collector(collector_id: str, interval_seconds: float, enabled: bool = True) -> ServiceCollector:
    return ServiceCollector(
        collector_id,
        interval_seconds,
        "climate",
        lambda: integrations.climate_integrations(),
        enabled=enabled,
    )


def weather_collector(collector_id: str, interval_seconds: float, enabled: bool = True) -> ServiceCollector:
    return ServiceCollector(
        collector_id,
        interval_seconds,
        "weather",
        lambda: integrations.weather_forecast(),
        enabled=enabled,
    )


def network_collector(collector_id: str, interval_seconds: float, enabled: bool = True) -> ServiceCollector:
    return ServiceCollector(
        collector_id,
        interval_seconds,
        "network",
        lambda: integrations.network_integrations(refresh_seconds=60),
        enabled=enabled,
    )


def security_collector(collector_id: str, interval_seconds: float, enabled: bool = True) -> ServiceCollector:
    return ServiceCollector(
        collector_id,
        interval_seconds,
        "homeassistant-security",
        lambda: integrations.security_integrations(refresh_seconds=60),
        enabled=enabled,
    )
