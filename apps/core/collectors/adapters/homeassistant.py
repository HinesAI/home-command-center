from __future__ import annotations

from typing import Any

import integrations
from collectors.base import Collector


class HomeAssistantCollector(Collector):
    collector_type = "homeassistant"

    def collect(self) -> dict[str, Any]:
        return integrations.home_assistant_entity_scan()

    def summarize(self, data: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(data, dict):
            return {"recordCount": 0, "configured": False}
        return {
            "configured": bool(data.get("configured")),
            "recordCount": int(data.get("entityCount") or 0),
            "domainCount": len(data.get("domains") or {}),
        }
