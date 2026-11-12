from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SettingField:
    key: str
    label: str
    group: str
    field_type: str
    description: str = ""
    default: str = ""
    options: tuple[str, ...] = ()
    secret: bool = False
    hot_reload: bool = True
    restart_required: bool = False
    cli_flag: str = ""


SETTING_GROUPS = {
    "collectors.runtime": {
        "label": "Collector runtime",
        "description": "Background collector scheduler. APIs stay on legacy routing until integration source is changed.",
    },
    "collectors.intervals": {
        "label": "Collector intervals",
        "description": "How often each collector refreshes its snapshot.",
    },
    "integration.routing": {
        "label": "Integration routing",
        "description": "Choose legacy integrations or collector snapshots per API. Default is legacy (unchanged dashboard behavior).",
    },
    "integrations.weather": {
        "label": "Weather",
        "description": "Open-Meteo location and cache settings.",
    },
    "integrations.homeassistant": {
        "label": "Home Assistant",
        "description": "Home Assistant URL and entity filters.",
    },
    "integrations.frigate": {
        "label": "Frigate",
        "description": "Frigate NVR and HCC Bridge (recording schedule / detections).",
    },
    "integrations.network": {
        "label": "UniFi / network",
        "description": "UniFi gateway API for WAN speedtests.",
    },
    "integrations.family": {
        "label": "Family calendar",
        "description": "CalDAV (Apple Calendar / Reminders) or local family board for wall kiosk.",
    },
    "core.fleet": {
        "label": "Fleet & agents",
        "description": "Heartbeat and refresh timing for enrolled agents.",
    },
    "core.platform": {
        "label": "Platform",
        "description": "Release channel and product labeling.",
    },
}

SOURCE_OPTIONS = ("legacy", "collector", "collector-only")
BOOL_OPTIONS = ("true", "false")


def _routing_fields(service: str, label: str) -> list[SettingField]:
    upper = service.upper()
    return [
        SettingField(
            key=f"HCC_SOURCE_{upper}",
            label=f"{label} API source",
            group="integration.routing",
            field_type="enum",
            options=SOURCE_OPTIONS,
            default="legacy",
            description=f"Where /api/v1/integrations/{service} reads data from.",
            hot_reload=True,
            cli_flag=f"--source-{service}",
        ),
        SettingField(
            key=f"HCC_LEGACY_{upper}",
            label=f"{label} legacy pull",
            group="integration.routing",
            field_type="enum",
            options=BOOL_OPTIONS,
            default="true",
            description=f"Allow direct legacy fetch for {service} when source is not collector-only.",
            hot_reload=True,
            cli_flag=f"--legacy-{service}",
        ),
    ]


SETTING_FIELDS: list[SettingField] = [
    SettingField(
        key="HCC_COLLECTORS_ENABLED",
        label="Collectors enabled",
        group="collectors.runtime",
        field_type="bool",
        options=BOOL_OPTIONS,
        default="true",
        description="Run background collectors and staging API.",
        hot_reload=False,
        restart_required=True,
        cli_flag="--collectors-enabled",
    ),
    SettingField(
        key="HCC_COLLECTORS_TICK_SECONDS",
        label="Scheduler tick (seconds)",
        group="collectors.runtime",
        field_type="int",
        default="5",
        description="How often the collector scheduler checks for due collectors.",
        hot_reload=False,
        restart_required=True,
        cli_flag="--collectors-tick-seconds",
    ),
    SettingField(
        key="HCC_COLLECTORS_CONFIG",
        label="Collector registry file",
        group="collectors.runtime",
        field_type="string",
        default="",
        description="Optional JSON registry path. Leave empty to use built-in defaults.",
        hot_reload=False,
        restart_required=True,
        cli_flag="--collectors-config",
    ),
    SettingField(
        key="HCC_INTEGRATION_SOURCE",
        label="Default integration source",
        group="integration.routing",
        field_type="enum",
        options=SOURCE_OPTIONS,
        default="legacy",
        description="Fallback when a per-service HCC_SOURCE_* value is not set.",
        hot_reload=True,
        cli_flag="--integration-source",
    ),
    SettingField(
        key="HCC_LEGACY_INTEGRATIONS",
        label="Legacy integrations (global)",
        group="integration.routing",
        field_type="enum",
        options=BOOL_OPTIONS,
        default="true",
        description="Global default for per-service legacy pulls.",
        hot_reload=True,
        cli_flag="--legacy-integrations",
    ),
    SettingField(
        key="HCC_INTEGRATION_SOURCE_DEBUG",
        label="Source debug metadata",
        group="integration.routing",
        field_type="bool",
        options=BOOL_OPTIONS,
        default="false",
        description="Include _integrationSource on integration API responses.",
        hot_reload=True,
        cli_flag="--integration-source-debug",
    ),
    SettingField(
        key="HCC_COLLECTOR_AGENT_INTERVAL",
        label="Fleet agents interval (seconds)",
        group="collectors.intervals",
        field_type="int",
        default="30",
        hot_reload=False,
        restart_required=True,
        cli_flag="--collector-interval-agents",
    ),
    SettingField(
        key="HCC_COLLECTOR_HA_INTERVAL",
        label="Home Assistant scan interval (seconds)",
        group="collectors.intervals",
        field_type="int",
        default="60",
        hot_reload=False,
        restart_required=True,
        cli_flag="--collector-interval-ha",
    ),
    SettingField(
        key="HCC_COLLECTOR_WEATHER_INTERVAL",
        label="Weather collector interval (seconds)",
        group="collectors.intervals",
        field_type="int",
        default="900",
        hot_reload=False,
        restart_required=True,
        cli_flag="--collector-interval-weather",
    ),
    SettingField(
        key="HCC_COLLECTOR_NETWORK_INTERVAL",
        label="Network collector interval (seconds)",
        group="collectors.intervals",
        field_type="int",
        default="60",
        hot_reload=False,
        restart_required=True,
        cli_flag="--collector-interval-network",
    ),
    SettingField(
        key="HCC_COLLECTOR_SECURITY_INTERVAL",
        label="Security collector interval (seconds)",
        group="collectors.intervals",
        field_type="int",
        default="60",
        hot_reload=False,
        restart_required=True,
        cli_flag="--collector-interval-security",
    ),
    SettingField(
        key="HCC_COLLECTOR_CLIMATE_INTERVAL",
        label="Climate collector interval (seconds)",
        group="collectors.intervals",
        field_type="int",
        default="30",
        hot_reload=False,
        restart_required=True,
        cli_flag="--collector-interval-climate",
    ),
    *_routing_fields("weather", "Weather"),
    *_routing_fields("network", "Network"),
    *_routing_fields("security", "Security"),
    *_routing_fields("climate", "Climate"),
    SettingField(
        key="HCC_WEATHER_LAT",
        label="Latitude",
        group="integrations.weather",
        field_type="float",
        default="33.9090855",
        hot_reload=True,
        cli_flag="--weather-lat",
    ),
    SettingField(
        key="HCC_WEATHER_LON",
        label="Longitude",
        group="integrations.weather",
        field_type="float",
        default="-87.3901102",
        hot_reload=True,
        cli_flag="--weather-lon",
    ),
    SettingField(
        key="HCC_WEATHER_LABEL",
        label="Location label",
        group="integrations.weather",
        field_type="string",
        default="",
        hot_reload=True,
        cli_flag="--weather-label",
    ),
    SettingField(
        key="HCC_WEATHER_TIMEZONE",
        label="Timezone",
        group="integrations.weather",
        field_type="string",
        default="America/Chicago",
        hot_reload=True,
        cli_flag="--weather-timezone",
    ),
    SettingField(
        key="HCC_WEATHER_CACHE_SECONDS",
        label="Weather cache (seconds)",
        group="integrations.weather",
        field_type="int",
        default="900",
        hot_reload=True,
        cli_flag="--weather-cache-seconds",
    ),
    SettingField(
        key="HCC_HA_URL",
        label="Home Assistant URL",
        group="integrations.homeassistant",
        field_type="string",
        default="http://192.168.1.20:8123",
        hot_reload=True,
        cli_flag="--ha-url",
    ),
    SettingField(
        key="HCC_HA_TOKEN",
        label="Home Assistant token",
        group="integrations.homeassistant",
        field_type="secret",
        default="",
        secret=True,
        hot_reload=True,
        cli_flag="--ha-token",
    ),
    SettingField(
        key="HCC_HA_CLIMATE_ENTITIES",
        label="Climate entities",
        group="integrations.homeassistant",
        field_type="string",
        default="",
        description="Comma-separated entity IDs. Empty = all climate.* entities.",
        hot_reload=True,
        cli_flag="--ha-climate-entities",
    ),
    SettingField(
        key="HCC_FRIGATE_URL",
        label="Frigate URL",
        group="integrations.frigate",
        field_type="string",
        default="https://192.168.1.30:8971",
        description="Authenticated UI/API. Use http://host:5000 when the unauthenticated API is published.",
        hot_reload=True,
        cli_flag="--frigate-url",
    ),
    SettingField(
        key="HCC_FRIGATE_BRIDGE_URL",
        label="Frigate HCC Bridge URL",
        group="integrations.frigate",
        field_type="string",
        default="",
        description="Optional recording bridge. Leave empty to read detections from the Frigate API.",
        hot_reload=True,
        cli_flag="--frigate-bridge-url",
    ),
    SettingField(
        key="HCC_FRIGATE_USER",
        label="Frigate user",
        group="integrations.frigate",
        field_type="string",
        default="",
        description="Required when Frigate URL is the authenticated port (8971).",
        hot_reload=True,
        cli_flag="--frigate-user",
    ),
    SettingField(
        key="HCC_FRIGATE_PASSWORD",
        label="Frigate password",
        group="integrations.frigate",
        field_type="secret",
        default="",
        secret=True,
        hot_reload=True,
        cli_flag="--frigate-password",
    ),
    SettingField(
        key="HCC_FRIGATE_VERIFY_SSL",
        label="Verify Frigate TLS",
        group="integrations.frigate",
        field_type="bool",
        default="false",
        description="Off for Frigate's default self-signed certificate.",
        hot_reload=True,
        cli_flag="--frigate-verify-ssl",
    ),
    SettingField(
        key="HCC_UNIFI_URL",
        label="UniFi URL",
        group="integrations.network",
        field_type="string",
        default="https://192.168.1.1",
        hot_reload=True,
        cli_flag="--unifi-url",
    ),
    SettingField(
        key="HCC_UNIFI_SITE",
        label="UniFi site",
        group="integrations.network",
        field_type="string",
        default="default",
        hot_reload=True,
        cli_flag="--unifi-site",
    ),
    SettingField(
        key="HCC_UNIFI_API_KEY",
        label="UniFi API key",
        group="integrations.network",
        field_type="secret",
        default="",
        secret=True,
        hot_reload=True,
        cli_flag="--unifi-api-key",
    ),
    SettingField(
        key="HCC_UNIFI_VERIFY_SSL",
        label="Verify UniFi SSL",
        group="integrations.network",
        field_type="bool",
        options=BOOL_OPTIONS,
        default="false",
        hot_reload=True,
        cli_flag="--unifi-verify-ssl",
    ),
    SettingField(
        key="HCC_NETWORK_CACHE_SECONDS",
        label="Network cache (seconds)",
        group="integrations.network",
        field_type="int",
        default="60",
        hot_reload=True,
        cli_flag="--network-cache-seconds",
    ),
    SettingField(
        key="HCC_CALDAV_URL",
        label="CalDAV server URL",
        group="integrations.family",
        field_type="string",
        default="",
        description="e.g. http://caldav:5232 or https://nextcloud.example/remote.php/dav",
        hot_reload=True,
    ),
    SettingField(
        key="HCC_CALDAV_USER",
        label="CalDAV username",
        group="integrations.family",
        field_type="string",
        default="",
        hot_reload=True,
    ),
    SettingField(
        key="HCC_CALDAV_PASSWORD",
        label="CalDAV password",
        group="integrations.family",
        field_type="secret",
        default="",
        secret=True,
        hot_reload=True,
    ),
    SettingField(
        key="HCC_CALDAV_EVENTS_CALENDAR",
        label="Events calendar path",
        group="integrations.family",
        field_type="string",
        default="",
        description="Collection path, e.g. /family/family/",
        hot_reload=True,
    ),
    SettingField(
        key="HCC_CALDAV_CHORES_CALENDAR",
        label="Chores calendar path",
        group="integrations.family",
        field_type="string",
        default="",
        description="Separate calendar for chores/todos, e.g. /family/chores/",
        hot_reload=True,
    ),
    SettingField(
        key="HCC_CALDAV_VERIFY_TLS",
        label="Verify CalDAV TLS",
        group="integrations.family",
        field_type="bool",
        options=BOOL_OPTIONS,
        default="true",
        hot_reload=True,
    ),
    SettingField(
        key="HCC_REFRESH_SECONDS",
        label="Core refresh interval (seconds)",
        group="core.fleet",
        field_type="int",
        default="120",
        hot_reload=False,
        restart_required=True,
        cli_flag="--refresh-seconds",
    ),
    SettingField(
        key="HCC_HEARTBEAT_TTL_SECONDS",
        label="Heartbeat stale TTL (seconds)",
        group="core.fleet",
        field_type="int",
        default="360",
        hot_reload=True,
        cli_flag="--heartbeat-ttl-seconds",
    ),
    SettingField(
        key="HCC_RELEASE_CHANNEL",
        label="Release channel",
        group="core.platform",
        field_type="string",
        default="stable",
        hot_reload=True,
        cli_flag="--release-channel",
    ),
    SettingField(
        key="HCC_PRODUCT_NAME",
        label="Product name",
        group="core.platform",
        field_type="string",
        default="Home Command Center",
        hot_reload=True,
        cli_flag="--product-name",
    ),
    SettingField(
        key="HCC_PRODUCT_SHORT_NAME",
        label="Product short name",
        group="core.platform",
        field_type="string",
        default="HCC",
        hot_reload=True,
        cli_flag="--product-short-name",
    ),
]

SETTINGS_BY_KEY = {field.key: field for field in SETTING_FIELDS}


def settings_schema() -> dict[str, Any]:
    groups = []
    for group_id, meta in SETTING_GROUPS.items():
        fields = []
        for field in SETTING_FIELDS:
            if field.group != group_id:
                continue
            fields.append(
                {
                    "key": field.key,
                    "label": field.label,
                    "type": field.field_type,
                    "description": field.description,
                    "default": field.default,
                    "options": list(field.options),
                    "secret": field.secret,
                    "hotReload": field.hot_reload,
                    "restartRequired": field.restart_required,
                    "cliFlag": field.cli_flag,
                }
            )
        if fields:
            groups.append(
                {
                    "id": group_id,
                    "label": meta["label"],
                    "description": meta["description"],
                    "fields": fields,
                }
            )
    return {"groups": groups}
