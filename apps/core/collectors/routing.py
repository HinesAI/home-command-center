from __future__ import annotations

import copy
import time
from typing import Any, Callable

import integrations
from collectors.migration import (
    SOURCE_COLLECTOR,
    SOURCE_COLLECTOR_ONLY,
    SOURCE_LEGACY,
    integration_source,
    legacy_pull_enabled,
    source_debug_enabled,
)

_runtime_resolver: Callable[[], Any] | None = None


def set_runtime_resolver(resolver: Callable[[], Any]):
    global _runtime_resolver
    _runtime_resolver = resolver


def _runtime():
    if _runtime_resolver is None:
        return None
    try:
        return _runtime_resolver()
    except Exception:
        return None


def _attach_debug(payload: dict[str, Any], service: str, source: str, collector_id: str | None = None) -> dict[str, Any]:
    if not source_debug_enabled():
        return payload
    enriched = copy.deepcopy(payload)
    enriched["_integrationSource"] = {
        "service": service,
        "source": source,
        "collectorId": collector_id,
        "legacyPullEnabled": legacy_pull_enabled(service),
    }
    return enriched


def _service_payload(data: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    payload = data.get("payload")
    return payload if isinstance(payload, dict) else None


def _collector_snapshot(collector_id: str) -> dict[str, Any] | None:
    runtime = _runtime()
    if runtime is None:
        return None
    detail = runtime.detail(collector_id, include_data=True)
    if not isinstance(detail, dict):
        return None
    if detail.get("status") != "ok":
        return None
    data = detail.get("data")
    return data if isinstance(data, dict) else None


def _unavailable_payload(service: str, collector_id: str, message: str) -> dict[str, Any]:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if service == "weather":
        return {
            "generatedAt": now,
            "refreshSeconds": integrations.WEATHER_CACHE_SECONDS,
            "provider": "open-meteo",
            "location": {
                "label": integrations.WEATHER_LABEL,
                "latitude": integrations.WEATHER_LAT,
                "longitude": integrations.WEATHER_LON,
                "timezone": integrations.WEATHER_TIMEZONE,
            },
            "current": None,
            "daily": [],
            "error": message,
        }
    if service == "network":
        return {
            "generatedAt": now,
            "refreshSeconds": integrations.NETWORK_CACHE_SECONDS,
            "provider": "unifi",
            "gatewayUrl": integrations.UNIFI_URL,
            "configured": bool(integrations.UNIFI_API_KEY),
            "online": False,
            "latencyMs": None,
            "gateway": None,
            "speedtest": None,
            "error": message,
            "cached": False,
        }
    if service == "security":
        return {
            "generatedAt": now,
            "refreshSeconds": 60,
            "totals": {
                "serviceCount": 0,
                "onlineCount": 0,
                "offlineCount": 0,
                "cameraCount": 0,
                "sensorCount": 0,
            },
            "services": [],
            "error": message,
        }
    return {
        "generatedAt": now,
        "refreshSeconds": integrations.CLIMATE_REFRESH_SECONDS,
        "haUrl": integrations.HA_URL,
        "configured": bool(integrations.HA_TOKEN),
        "haOnline": False,
        "thermostats": [],
        "totals": {"thermostatCount": 0, "onlineCount": 0, "activeCount": 0},
        "error": message,
    }


def resolve_integration(
    service: str,
    collector_id: str,
    legacy_fn: Callable[[], dict[str, Any]],
    extract: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    source = integration_source(service)
    extractor = extract or (lambda data: data)

    if source in {SOURCE_COLLECTOR, SOURCE_COLLECTOR_ONLY}:
        snapshot = _collector_snapshot(collector_id)
        if snapshot is not None:
            payload = extractor(snapshot)
            if isinstance(payload, dict):
                return _attach_debug(payload, service, SOURCE_COLLECTOR, collector_id)

        if source == SOURCE_COLLECTOR_ONLY:
            message = f"collector snapshot unavailable for {collector_id}"
            return _attach_debug(_unavailable_payload(service, collector_id, message), service, SOURCE_COLLECTOR_ONLY, collector_id)

    if legacy_pull_enabled(service):
        payload = legacy_fn()
        return _attach_debug(payload, service, SOURCE_LEGACY, None)

    message = f"legacy integration disabled for {service} and collector snapshot unavailable"
    return _attach_debug(_unavailable_payload(service, collector_id, message), service, source, collector_id)


def weather_forecast(refresh_seconds=None):
    return resolve_integration(
        "weather",
        "weather",
        lambda: integrations.weather_forecast(refresh_seconds=refresh_seconds),
        extract=_service_payload,
    )


def network_integrations(refresh_seconds=None):
    return resolve_integration(
        "network",
        "network",
        lambda: integrations.network_integrations(refresh_seconds=refresh_seconds),
        extract=_service_payload,
    )


def security_integrations(refresh_seconds=60):
    return resolve_integration(
        "security",
        "security",
        lambda: integrations.security_integrations(refresh_seconds=refresh_seconds),
        extract=_service_payload,
    )


def climate_integrations(refresh_seconds=None):
    return resolve_integration(
        "climate",
        "climate",
        lambda: integrations.climate_integrations(refresh_seconds=refresh_seconds),
        extract=_service_payload,
    )
