from __future__ import annotations

import time
from typing import Any, Callable

from collectors.base import Collector


class AgentFleetCollector(Collector):
    collector_type = "agent"

    def __init__(
        self,
        collector_id: str,
        interval_seconds: float,
        fleet_snapshot_fn: Callable[[], dict[str, Any]],
        heartbeat_ttl_seconds: float,
        enabled: bool = True,
    ):
        super().__init__(collector_id, interval_seconds, enabled=enabled)
        self._fleet_snapshot_fn = fleet_snapshot_fn
        self._heartbeat_ttl_seconds = heartbeat_ttl_seconds

    def collect(self) -> dict[str, Any]:
        raw = self._fleet_snapshot_fn() or {}
        now = time.time()
        nodes = []
        for node_id, record in raw.items():
            if not isinstance(record, dict):
                continue
            snapshot = record.get("snapshot") if isinstance(record.get("snapshot"), dict) else {}
            node = snapshot.get("node") if isinstance(snapshot.get("node"), dict) else {}
            last_seen_ts = float(record.get("lastSeenTs") or 0)
            age_seconds = max(0.0, now - last_seen_ts) if last_seen_ts else None
            online = last_seen_ts > 0 and age_seconds is not None and age_seconds <= self._heartbeat_ttl_seconds
            nodes.append(
                {
                    "nodeId": str(node_id),
                    "agentId": str(record.get("agentId") or ""),
                    "agentVersion": str(record.get("agentVersion") or node.get("agentVersion") or ""),
                    "hostname": str(node.get("hostname") or node_id),
                    "hostRole": str(node.get("hostRole") or ""),
                    "deviceCategory": str(node.get("deviceCategory") or ""),
                    "platform": str(node.get("platform") or ""),
                    "lastSeen": record.get("lastSeen"),
                    "lastSeenTs": last_seen_ts or None,
                    "ageSeconds": round(age_seconds, 1) if age_seconds is not None else None,
                    "online": online,
                    "serviceCount": len(snapshot.get("services") or []),
                    "containerCount": len(snapshot.get("containers") or []),
                }
            )
        nodes.sort(key=lambda row: (not row["online"], row.get("hostname") or row["nodeId"]))
        online_count = sum(1 for row in nodes if row["online"])
        return {
            "source": "agent-heartbeat",
            "nodeCount": len(nodes),
            "onlineCount": online_count,
            "staleCount": len(nodes) - online_count,
            "nodes": nodes,
        }

    def summarize(self, data: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(data, dict):
            return {"recordCount": 0}
        return {
            "recordCount": int(data.get("nodeCount") or 0),
            "onlineCount": int(data.get("onlineCount") or 0),
            "staleCount": int(data.get("staleCount") or 0),
        }
