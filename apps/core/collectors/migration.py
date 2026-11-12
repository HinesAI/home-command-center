from __future__ import annotations

import os

# Services that can be routed between legacy integrations and collector snapshots.
MIGRATABLE_SERVICES = ("weather", "network", "security", "climate")

SOURCE_LEGACY = "legacy"
SOURCE_COLLECTOR = "collector"
SOURCE_COLLECTOR_ONLY = "collector-only"

SERVICE_COLLECTOR_IDS = {
    "weather": "weather",
    "network": "network",
    "security": "security",
    "climate": "climate",
}


def _normalize_source(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("_", "-")
    if normalized in {"collector-only", "collectors-only", "only"}:
        return SOURCE_COLLECTOR_ONLY
    if normalized in {"collector", "collectors"}:
        return SOURCE_COLLECTOR
    return SOURCE_LEGACY


def integration_source(service: str) -> str:
    service_key = str(service or "").strip().lower()
    specific = os.environ.get(f"HCC_SOURCE_{service_key.upper()}", "").strip()
    if specific:
        return _normalize_source(specific)
    return _normalize_source(os.environ.get("HCC_INTEGRATION_SOURCE", SOURCE_LEGACY))


def legacy_pull_enabled(service: str) -> bool:
    if integration_source(service) == SOURCE_COLLECTOR_ONLY:
        return False
    service_key = str(service or "").strip().lower()
    specific = os.environ.get(f"HCC_LEGACY_{service_key.upper()}", "").strip().lower()
    if specific in {"false", "0", "no"}:
        return False
    if specific in {"true", "1", "yes"}:
        return True
    return os.environ.get("HCC_LEGACY_INTEGRATIONS", "true").lower() not in {"false", "0", "no"}


def source_debug_enabled() -> bool:
    return os.environ.get("HCC_INTEGRATION_SOURCE_DEBUG", "false").lower() in {"true", "1", "yes"}


def migration_status() -> dict:
    services = []
    for service in MIGRATABLE_SERVICES:
        source = integration_source(service)
        services.append(
            {
                "service": service,
                "collectorId": SERVICE_COLLECTOR_IDS.get(service),
                "source": source,
                "legacyPullEnabled": legacy_pull_enabled(service),
                "apiUsesCollectors": source in {SOURCE_COLLECTOR, SOURCE_COLLECTOR_ONLY},
                "legacyDisabled": not legacy_pull_enabled(service),
            }
        )
    migrated = [row["service"] for row in services if row["source"] == SOURCE_COLLECTOR_ONLY]
    return {
        "defaultSource": _normalize_source(os.environ.get("HCC_INTEGRATION_SOURCE", SOURCE_LEGACY)),
        "debug": source_debug_enabled(),
        "fullyMigrated": len(migrated) == len(MIGRATABLE_SERVICES),
        "migratedServices": migrated,
        "services": services,
    }
