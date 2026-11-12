from __future__ import annotations

import json
import logging
import os
from typing import Any, Callable

import integrations
from collectors.adapters.agents import AgentFleetCollector
from collectors.adapters.homeassistant import HomeAssistantCollector
from collectors.adapters.services import climate_collector, network_collector, security_collector, weather_collector
from collectors.runtime import CollectorRuntime

logger = logging.getLogger("hcc.collectors")

_runtime = None


def collectors_enabled() -> bool:
    return os.environ.get("HCC_COLLECTORS_ENABLED", "true").lower() not in {"0", "false", "no"}


def _config_path() -> str:
    configured = os.environ.get("HCC_COLLECTORS_CONFIG", "").strip()
    if configured:
        return configured
    return os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "deploy", "collectors.example.json")
    )


def _load_json_config(path: str) -> dict[str, Any]:
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("unable to read collector config %s: %s", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def _collector_enabled(config: dict[str, Any], default: bool = True) -> bool:
    if "enabled" not in config:
        return default
    return bool(config.get("enabled"))


def default_collector_specs() -> list[dict[str, Any]]:
    ha_configured = bool(integrations.HA_TOKEN)
    unifi_configured = bool(integrations.UNIFI_API_KEY)
    return [
        {
            "id": "fleet-agents",
            "type": "agent",
            "intervalSeconds": int(os.environ.get("HCC_COLLECTOR_AGENT_INTERVAL", "30")),
            "enabled": True,
        },
        {
            "id": "homeassistant",
            "type": "homeassistant",
            "intervalSeconds": int(os.environ.get("HCC_COLLECTOR_HA_INTERVAL", "60")),
            "enabled": ha_configured,
        },
        {
            "id": "weather",
            "type": "service",
            "service": "weather",
            "intervalSeconds": int(os.environ.get("HCC_COLLECTOR_WEATHER_INTERVAL", str(integrations.WEATHER_CACHE_SECONDS))),
            "enabled": True,
        },
        {
            "id": "network",
            "type": "service",
            "service": "network",
            "intervalSeconds": int(os.environ.get("HCC_COLLECTOR_NETWORK_INTERVAL", str(integrations.NETWORK_CACHE_SECONDS))),
            "enabled": unifi_configured,
        },
        {
            "id": "security",
            "type": "service",
            "service": "security",
            "intervalSeconds": int(os.environ.get("HCC_COLLECTOR_SECURITY_INTERVAL", "60")),
            "enabled": True,
        },
        {
            "id": "climate",
            "type": "service",
            "service": "climate",
            "intervalSeconds": int(os.environ.get("HCC_COLLECTOR_CLIMATE_INTERVAL", str(integrations.CLIMATE_REFRESH_SECONDS))),
            "enabled": bool(integrations.HA_TOKEN),
        },
    ]


def build_collector(spec: dict[str, Any], fleet_snapshot_fn: Callable[[], dict[str, Any]], heartbeat_ttl_seconds: float):
    collector_id = str(spec.get("id") or "").strip()
    collector_type = str(spec.get("type") or "").strip().lower()
    interval_seconds = float(spec.get("intervalSeconds") or 60)
    enabled = _collector_enabled(spec, default=True)

    if collector_type == "agent":
        return AgentFleetCollector(
            collector_id or "fleet-agents",
            interval_seconds,
            fleet_snapshot_fn,
            heartbeat_ttl_seconds,
            enabled=enabled,
        )
    if collector_type == "homeassistant":
        return HomeAssistantCollector(collector_id or "homeassistant", interval_seconds, enabled=enabled)
    if collector_type == "service":
        service_name = str(spec.get("service") or collector_id or "").strip().lower()
        if service_name == "weather":
            return weather_collector(collector_id or "weather", interval_seconds, enabled=enabled)
        if service_name == "network":
            return network_collector(collector_id or "network", interval_seconds, enabled=enabled)
        if service_name == "climate":
            return climate_collector(collector_id or "climate", interval_seconds, enabled=enabled)
        if service_name in {"security", "homeassistant-security"}:
            return security_collector(collector_id or "security", interval_seconds, enabled=enabled)
    raise ValueError(f"unsupported collector type: {collector_type or collector_id}")


def build_runtime(
    fleet_snapshot_fn: Callable[[], dict[str, Any]],
    heartbeat_ttl_seconds: float,
) -> CollectorRuntime | None:
    if not collectors_enabled():
        return None

    config = _load_json_config(_config_path())
    specs = config.get("collectors") if isinstance(config.get("collectors"), list) else default_collector_specs()
    collectors = []
    for spec in specs:
        if not isinstance(spec, dict):
            continue
        try:
            collectors.append(build_collector(spec, fleet_snapshot_fn, heartbeat_ttl_seconds))
        except ValueError as exc:
            logger.warning("skipping collector spec %s: %s", spec, exc)

    tick_seconds = float(
        config.get("tickSeconds")
        if isinstance(config, dict) and config.get("tickSeconds") is not None
        else os.environ.get("HCC_COLLECTORS_TICK_SECONDS", "5")
    )
    return CollectorRuntime(collectors, tick_seconds=tick_seconds)


def get_runtime(
    fleet_snapshot_fn: Callable[[], dict[str, Any]],
    heartbeat_ttl_seconds: float,
) -> CollectorRuntime | None:
    global _runtime
    if _runtime is None:
        _runtime = build_runtime(fleet_snapshot_fn, heartbeat_ttl_seconds)
    return _runtime
