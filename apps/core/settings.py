from __future__ import annotations

import json
import os
import re
import time
from typing import Any

from settings_registry import SETTINGS_BY_KEY, settings_schema

_ENV_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def settings_file_path() -> str:
    return os.environ.get("HCC_SETTINGS_FILE", "/app/data/hcc-settings.env").strip() or "/app/data/hcc-settings.env"


def load_runtime_settings_file() -> dict[str, str]:
    """Overlay persisted GUI/CLI settings into the process environment."""
    path = settings_file_path()
    loaded = {}
    if not os.path.exists(path):
        return loaded
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                match = _ENV_LINE.match(line)
                if not match:
                    continue
                key, value = match.group(1), match.group(2)
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                os.environ[key] = value
                loaded[key] = value
    except OSError:
        return loaded
    return loaded


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "••••"
    return f"{value[:2]}••••{value[-2:]}"


def current_value(field_key: str) -> str:
    return os.environ.get(field_key, SETTINGS_BY_KEY[field_key].default if field_key in SETTINGS_BY_KEY else "")


def settings_values() -> dict[str, Any]:
    values = {}
    for key, field in SETTINGS_BY_KEY.items():
        raw = os.environ.get(key, field.default)
        if field.secret:
            values[key] = {
                "value": _mask_secret(raw),
                "configured": bool(str(raw or "").strip()),
                "secret": True,
            }
        else:
            values[key] = {
                "value": str(raw if raw is not None else ""),
                "configured": bool(str(raw or "").strip()) if field.field_type == "secret" else True,
                "secret": False,
            }
    return values


def validate_updates(updates: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
    normalized: dict[str, str] = {}
    errors: list[str] = []
    for key, raw_value in updates.items():
        field = SETTINGS_BY_KEY.get(key)
        if field is None:
            errors.append(f"unknown setting: {key}")
            continue
        if raw_value is None:
            continue
        value = str(raw_value).strip()
        if field.secret and value in {"", "••••", "__UNCHANGED__"}:
            continue
        if field.field_type == "bool":
            value = value.lower()
            if value not in {"true", "false", "1", "0", "yes", "no"}:
                errors.append(f"{key} must be true or false")
                continue
            value = "true" if value in {"true", "1", "yes"} else "false"
        elif field.field_type == "enum" and field.options:
            candidate = value.lower().replace("_", "-")
            allowed = {option.lower() for option in field.options}
            if candidate not in allowed:
                errors.append(f"{key} must be one of: {', '.join(field.options)}")
                continue
            value = next(option for option in field.options if option.lower() == candidate)
        elif field.field_type == "int":
            try:
                value = str(int(value))
            except ValueError:
                errors.append(f"{key} must be an integer")
                continue
        elif field.field_type == "float":
            try:
                value = str(float(value))
            except ValueError:
                errors.append(f"{key} must be a number")
                continue
        normalized[key] = value
    return normalized, errors


def read_persisted_settings() -> dict[str, str]:
    path = settings_file_path()
    persisted = {}
    if not os.path.exists(path):
        return persisted
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                match = _ENV_LINE.match(line)
                if match:
                    persisted[match.group(1)] = match.group(2)
    except OSError:
        return persisted
    return persisted


def write_persisted_settings(updates: dict[str, str]) -> str:
    path = settings_file_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    persisted = read_persisted_settings()
    persisted.update(updates)
    lines = [
        "# HCC runtime settings overlay (managed by Admin GUI / hcc-settings CLI)",
        f"# updatedAt={time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
        "",
    ]
    for key in sorted(persisted):
        if key not in SETTINGS_BY_KEY:
            continue
        value = persisted[key]
        if " " in value or "#" in value:
            value = json.dumps(value)
        lines.append(f"{key}={value}")
    lines.append("")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    return path


def apply_settings(updates: dict[str, Any]) -> dict[str, Any]:
    normalized, errors = validate_updates(updates)
    if errors:
        return {"ok": False, "errors": errors}

    hot_reload_keys = []
    restart_required = False
    for key, value in normalized.items():
        field = SETTINGS_BY_KEY[key]
        os.environ[key] = value
        if field.hot_reload:
            hot_reload_keys.append(key)
        if field.restart_required:
            restart_required = True

    path = write_persisted_settings(normalized) if normalized else settings_file_path()
    return {
        "ok": True,
        "updated": sorted(normalized.keys()),
        "hotReloadKeys": hot_reload_keys,
        "restartRequired": restart_required,
        "settingsFile": path,
    }


def apply_greenlight_migration(services: list[str] | None = None) -> dict[str, Any]:
    from collectors.migration import MIGRATABLE_SERVICES

    targets = [service for service in (services or list(MIGRATABLE_SERVICES)) if service in MIGRATABLE_SERVICES]
    updates = {"HCC_COLLECTORS_ENABLED": "true"}
    for service in targets:
        upper = service.upper()
        updates[f"HCC_SOURCE_{upper}"] = "collector-only"
        updates[f"HCC_LEGACY_{upper}"] = "false"
    result = apply_settings(updates)
    result["action"] = "greenlight-collectors"
    result["services"] = targets
    return result


def apply_rollback_migration(services: list[str] | None = None) -> dict[str, Any]:
    from collectors.migration import MIGRATABLE_SERVICES

    targets = [service for service in (services or list(MIGRATABLE_SERVICES)) if service in MIGRATABLE_SERVICES]
    updates = {}
    for service in targets:
        upper = service.upper()
        updates[f"HCC_SOURCE_{upper}"] = "legacy"
        updates[f"HCC_LEGACY_{upper}"] = "true"
    result = apply_settings(updates)
    result["action"] = "rollback-collectors"
    result["services"] = targets
    return result


def admin_settings_payload(collectors_index: dict[str, Any] | None, migration_status: dict[str, Any]) -> dict[str, Any]:
    return {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "settingsFile": settings_file_path(),
        "schema": settings_schema(),
        "values": settings_values(),
        "migration": migration_status,
        "collectors": collectors_index or {"enabled": False, "collectors": []},
        "actions": [
            {
                "id": "greenlight-collectors",
                "label": "Greenlight collector migration",
                "description": "Switch weather, network, security, and climate APIs to collector-only and disable legacy pulls.",
            },
            {
                "id": "rollback-collectors",
                "label": "Rollback collector migration",
                "description": "Restore legacy integration routing for migrated services.",
            },
        ],
    }
