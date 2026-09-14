#!/usr/bin/env python3
import json
import logging
import os
import shutil
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import auth
import branding
import integrations

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("hcc.core")


HOST = os.environ.get("HCC_CORE_HOST", "0.0.0.0")
PORT = int(os.environ.get("HCC_CORE_PORT", "8080"))
REFRESH_SECONDS = float(os.environ.get("HCC_REFRESH_SECONDS", "120"))
HEARTBEAT_TTL_SECONDS = int(os.environ.get("HCC_HEARTBEAT_TTL_SECONDS", "360"))
NODE_HISTORY_LIMIT = int(os.environ.get("HCC_NODE_HISTORY_LIMIT", "240"))
FLEET_STATE_PATH = os.environ.get("HCC_FLEET_STATE_PATH", "/app/data/fleet-state.json")
ACTION_STATE_PATH = os.environ.get("HCC_ACTION_STATE_PATH", "/app/data/action-state.json")

STORAGE_PATHS = [p.strip() for p in os.environ.get("HCC_STORAGE_PATHS", "/,/srv,/mnt/storage,/media/storage").split(",") if p.strip()]
SERVICES = [s.strip() for s in os.environ.get("HCC_SERVICES", "docker,ssh,ufw").split(",") if s.strip()]
CONTAINERS = [c.strip() for c in os.environ.get("HCC_CONTAINERS", "nextcloud,jellyfin,mariadb,postgres,redis,nginx,traefik,caddy").split(",") if c.strip()]

_last_cpu = None
_last_net = None
_last_net_ts = None
_agent_nodes = {}
_agent_nodes_lock = threading.Lock()
_action_queue = {}
_action_log = []


def load_fleet_state():
    global _agent_nodes
    if not FLEET_STATE_PATH:
        return
    try:
        with open(FLEET_STATE_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            return
        with _agent_nodes_lock:
            _agent_nodes = data
        logger.info("loaded %s fleet node(s) from %s", len(data), FLEET_STATE_PATH)
    except FileNotFoundError:
        return
    except Exception as exc:
        logger.warning("failed to load fleet state: %s", exc)


def save_fleet_state():
    if not FLEET_STATE_PATH:
        return
    try:
        directory = os.path.dirname(FLEET_STATE_PATH)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with _agent_nodes_lock:
            snapshot = json.loads(json.dumps(_agent_nodes))
        temp_path = f"{FLEET_STATE_PATH}.tmp"
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(snapshot, handle)
        os.replace(temp_path, FLEET_STATE_PATH)
    except Exception as exc:
        logger.warning("failed to save fleet state: %s", exc)


def load_action_state():
    global _action_queue, _action_log
    if not ACTION_STATE_PATH:
        return
    try:
        with open(ACTION_STATE_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            return
        with _action_lock:
            queue = data.get("queue")
            log = data.get("log")
            if isinstance(queue, dict):
                _action_queue = queue
            if isinstance(log, list):
                _action_log = log[-500:]
        logger.info(
            "loaded action state: %s queued node(s), %s log entries",
            len(_action_queue),
            len(_action_log),
        )
    except FileNotFoundError:
        return
    except Exception as exc:
        logger.warning("failed to load action state: %s", exc)


def save_action_state():
    if not ACTION_STATE_PATH:
        return
    try:
        directory = os.path.dirname(ACTION_STATE_PATH)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with _action_lock:
            snapshot = {
                "queue": json.loads(json.dumps(_action_queue)),
                "log": json.loads(json.dumps(_action_log[-500:])),
            }
        temp_path = f"{ACTION_STATE_PATH}.tmp"
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(snapshot, handle)
        os.replace(temp_path, ACTION_STATE_PATH)
    except Exception as exc:
        logger.warning("failed to save action state: %s", exc)


_action_lock = threading.Lock()

RELEASES_PATH = os.environ.get(
    "HCC_AGENT_RELEASES_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_releases.json"),
)
WEB_BASE_URL = os.environ.get("HCC_WEB_BASE_URL", "http://192.168.1.10:3000/downloads")
VERSION_PATH = os.environ.get(
    "HCC_VERSION_PATH",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "VERSION")),
)
_agent_releases_cache = {"loadedAt": 0.0, "data": {}}


def hcc_version():
    configured = os.environ.get("HCC_VERSION", "").strip()
    if configured:
        return configured
    try:
        with open(VERSION_PATH, "r", encoding="utf-8") as handle:
            return handle.read().strip() or "0.0.0-dev"
    except OSError:
        return "0.0.0-dev"


def load_agent_releases():
    now = time.time()
    if now - _agent_releases_cache["loadedAt"] < 5 and _agent_releases_cache["data"]:
        return _agent_releases_cache["data"]
    try:
        with open(RELEASES_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {"platforms": {}}
    _agent_releases_cache["loadedAt"] = now
    _agent_releases_cache["data"] = data
    return data


def normalize_platform(platform):
    value = str(platform or "").strip().lower()
    if value in {"windows", "linux"}:
        return value
    if value.startswith("win"):
        return "windows"
    return "linux"


def release_for_platform(platform, version=None):
    releases = load_agent_releases()
    platform_key = normalize_platform(platform)
    platform_cfg = releases.get("platforms", {}).get(platform_key, {})
    versions = platform_cfg.get("versions", {})
    target_version = str(version or platform_cfg.get("latest") or "").strip()
    if not target_version:
        return None
    entry = versions.get(target_version)
    if not entry:
        return None
    package_url = entry.get("packageUrl") or ""
    if package_url.startswith("/"):
        base = releases.get("webBaseUrl") or WEB_BASE_URL
        package_url = f"{base.rstrip('/')}{package_url}"
    return {
        "platform": platform_key,
        "version": target_version,
        "label": entry.get("label") or target_version,
        "packageUrl": package_url,
        "sha256": str(entry.get("sha256") or ""),
        "latest": str(platform_cfg.get("latest") or target_version),
    }


def node_agent_version(record):
    if not isinstance(record, dict):
        return "unknown"
    explicit = record.get("agentVersion")
    if explicit:
        return str(explicit)
    snap = record.get("snapshot", {})
    node = snap.get("node", {}) if isinstance(snap, dict) else {}
    if isinstance(node, dict) and node.get("agentVersion"):
        return str(node.get("agentVersion"))
    return "unknown"


def node_platform_from_record(record):
    snap = record.get("snapshot", {}) if isinstance(record, dict) else {}
    node = snap.get("node", {}) if isinstance(snap, dict) else {}
    return normalize_platform(node.get("platform") or record.get("platform") or "linux")


def agent_self_update_status():
    pending_by_node = {}
    last_by_node = {}
    with _action_lock:
        for node_id, entries in _action_queue.items():
            pending = [
                item
                for item in entries
                if item.get("actionId") == "agent.self_update"
            ]
            if pending:
                pending_by_node[node_id] = pending
        for item in reversed(_action_log):
            if item.get("actionId") != "agent.self_update":
                continue
            node_id = item.get("nodeId")
            if node_id and node_id not in last_by_node:
                last_by_node[node_id] = item
    return pending_by_node, last_by_node


def admin_agent_inventory():
    releases = load_agent_releases()
    now = time.time()
    pending_by_node, last_by_node = agent_self_update_status()
    items = []
    with _agent_nodes_lock:
        for node_id, record in _agent_nodes.items():
            summary = snapshot_node_summary(node_id, record, now)
            platform = node_platform_from_record(record)
            current_version = node_agent_version(record)
            latest_release = release_for_platform(platform)
            latest_version = latest_release["version"] if latest_release else "unknown"
            update_available = (
                latest_release is not None
                and current_version not in {"unknown", ""}
                and current_version != latest_version
            )
            pending_updates = pending_by_node.get(node_id, [])
            last_update = last_by_node.get(node_id)
            update_mismatch = (
                last_update is not None
                and last_update.get("status") == "completed"
                and update_available
            )
            items.append(
                {
                    "nodeId": node_id,
                    "agentId": record.get("agentId"),
                    "hostname": summary.get("hostname") or node_id,
                    "platform": platform,
                    "hostRole": summary.get("hostRole"),
                    "deviceCategory": summary.get("deviceCategory"),
                    "agentVersion": current_version,
                    "latestVersion": latest_version,
                    "updateAvailable": update_available,
                    "stale": summary.get("stale", False),
                    "lastSeen": summary.get("lastSeen"),
                    "pendingUpdateCount": len(pending_updates),
                    "pendingUpdateVersion": (
                        pending_updates[-1].get("params", {}).get("version")
                        if pending_updates
                        else None
                    ),
                    "lastUpdateStatus": last_update.get("status") if last_update else None,
                    "lastUpdateMessage": last_update.get("message") if last_update else None,
                    "lastUpdateAt": (
                        last_update.get("completedAt")
                        or last_update.get("deliveredAt")
                        or last_update.get("queuedAt")
                        if last_update
                        else None
                    ),
                    "updateMismatch": update_mismatch,
                }
            )
    items.sort(key=lambda row: (row["platform"], row["deviceCategory"], row["hostname"]))
    return items


def admin_release_summary():
    releases = load_agent_releases()
    summary = []
    for platform_key in ("windows", "linux"):
        platform_cfg = releases.get("platforms", {}).get(platform_key, {})
        latest = release_for_platform(platform_key)
        inventory = admin_agent_inventory()
        platform_nodes = [row for row in inventory if row["platform"] == platform_key]
        outdated = [row for row in platform_nodes if row["updateAvailable"]]
        summary.append(
            {
                "platform": platform_key,
                "latestVersion": latest["version"] if latest else "unknown",
                "latestLabel": latest["label"] if latest else "",
                "packageUrl": latest["packageUrl"] if latest else "",
                "sha256": latest["sha256"] if latest else "",
                "nodeCount": len(platform_nodes),
                "outdatedCount": len(outdated),
                "versions": platform_cfg.get("versions", {}),
            }
        )
    return summary


def resolve_update_targets(body):
    inventory = {row["nodeId"]: row for row in admin_agent_inventory()}
    explicit_ids = [str(node_id) for node_id in (body.get("nodeIds") or []) if str(node_id)]
    unknown_ids = []
    if explicit_ids:
        targets = []
        for node_id in explicit_ids:
            if node_id in inventory:
                targets.append(inventory[node_id])
            else:
                unknown_ids.append(node_id)
        return targets, unknown_ids

    platform_filter = str(body.get("platform") or "all").lower()
    group_filter = str(body.get("group") or "all").lower()
    host_role_filter = str(body.get("hostRole") or "").lower()
    only_outdated = bool(body.get("onlyOutdated", True))
    rows = list(inventory.values())

    if platform_filter not in {"", "all"}:
        rows = [row for row in rows if row["platform"] == normalize_platform(platform_filter)]
    if group_filter == "servers":
        rows = [row for row in rows if row["deviceCategory"] == "server"]
    elif group_filter == "clients":
        rows = [row for row in rows if row["deviceCategory"] == "client"]
    if host_role_filter:
        rows = [row for row in rows if str(row.get("hostRole") or "").lower() == host_role_filter]
    if only_outdated:
        rows = [row for row in rows if row["updateAvailable"]]
    if body.get("excludeStale", True):
        rows = [row for row in rows if not row["stale"]]
    return rows, unknown_ids


def push_agent_updates(body, requested_by="admin-ui"):
    version = body.get("version")
    targets, unknown_ids = resolve_update_targets(body)
    queued = []
    skipped = []
    for row in targets:
        release = release_for_platform(row["platform"], version=version)
        if not release:
            skipped.append({"nodeId": row["nodeId"], "reason": "release not found"})
            continue
        if row["agentVersion"] == release["version"]:
            skipped.append(
                {
                    "nodeId": row["nodeId"],
                    "reason": f"already on version {release['version']}",
                }
            )
            continue
        if row["stale"]:
            skipped.append({"nodeId": row["nodeId"], "reason": "node stale"})
            continue
        entry = queue_action(
            row["nodeId"],
            "agent.self_update",
            params={
                "version": release["version"],
                "packageUrl": release["packageUrl"],
                "sha256": release["sha256"],
                "platform": release["platform"],
            },
            requested_by=requested_by,
        )
        queued.append(entry)
    return {
        "queuedCount": len(queued),
        "skippedCount": len(skipped),
        "queued": queued,
        "skipped": skipped,
        "targetsResolved": len(targets),
        "unknownNodeIds": unknown_ids,
    }


def now_iso_utc():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def device_category(host_role, node=None):
    node = node or {}
    explicit = node.get("deviceCategory")
    if explicit in {"server", "client"}:
        return explicit
    if host_role == "windows-client":
        return "client"
    return "server"


def normalize_storage_list(storage):
    if isinstance(storage, dict):
        if storage.get("path") or storage.get("totalBytes") or storage.get("usedBytes"):
            return [storage]
        return []
    if not isinstance(storage, list):
        return []
    return [item for item in storage if isinstance(item, dict)]


def storage_totals_from_snapshot(storage):
    rows = normalize_storage_list(storage)
    storage_total = sum(int(item.get("totalBytes", 0)) for item in rows)
    storage_used = sum(int(item.get("usedBytes", 0)) for item in rows)
    storage_percent = round((storage_used * 100) / max(1, storage_total), 1)
    return storage_total, storage_used, storage_percent


def snapshot_node_summary(node_id, record, now_ts):
    snap = record.get("snapshot", {})
    node = snap.get("node", {})
    system = snap.get("system", {})
    memory = system.get("memory", {})
    network = system.get("network", {})
    cpu_runtime = system.get("cpu", {})
    cpu = node.get("cpu") or {}
    storage = snap.get("storage", [])
    storage_detail = snap.get("storageDetail") or {}
    detail_totals = storage_detail.get("totals") if isinstance(storage_detail, dict) else {}
    hardware = node.get("hardware", {})

    storage_total, storage_used, storage_percent = storage_totals_from_snapshot(storage)
    if storage_total <= 0 and isinstance(detail_totals, dict):
        storage_total = int(detail_totals.get("totalBytes", 0))
        storage_used = int(detail_totals.get("usedBytes", 0))
        storage_percent = float(detail_totals.get("percent", 0.0))
    logical_cpus = int(cpu.get("logicalCpus") or cpu.get("threads") or cpu.get("cores") or 0)
    physical_cores = int(cpu.get("physicalCores") or logical_cpus or 0)
    host_role = node.get("hostRole", "unknown")

    return {
        "nodeId": node_id,
        "hostname": node.get("hostname") or node_id,
        "platform": node.get("platform", "unknown"),
        "hostRole": host_role,
        "deviceCategory": device_category(host_role, node),
        "cpuModel": cpu.get("model"),
        "cpuLogical": logical_cpus,
        "cpuPhysical": physical_cores,
        "cpuSockets": int(cpu.get("sockets") or 0),
        "os": node.get("os", {}),
        "hardware": {
            "virtualizationType": hardware.get("virtualizationType", "unknown"),
            "isPhysical": bool(hardware.get("isPhysical", False)),
            "isVirtualMachine": bool(hardware.get("isVirtualMachine", False)),
            "isContainer": bool(hardware.get("isContainer", False)),
        },
        "uptimeSec": int(node.get("uptimeSec", 0)),
        "ips": node.get("ips", []),
        "resources": {
            "cpuPercent": float(system.get("cpuPercent", 0.0)),
            "cpuLogical": logical_cpus,
            "cpuPhysical": physical_cores,
            "cpuSockets": int(cpu.get("sockets") or 0),
            "load1": float(cpu_runtime.get("load1", 0.0)),
            "load5": float(cpu_runtime.get("load5", 0.0)),
            "load15": float(cpu_runtime.get("load15", 0.0)),
            "queueLength": float(cpu_runtime.get("queueLength", cpu_runtime.get("load1", 0.0))),
            "memoryPercent": float(memory.get("percent", 0.0)),
            "memoryUsedBytes": int(memory.get("usedBytes", 0)),
            "memoryTotalBytes": int(memory.get("totalBytes", 0)),
            "memoryAvailableBytes": int(memory.get("availableBytes", 0)),
            "swapUsedBytes": int(memory.get("swapUsedBytes", 0)),
            "swapTotalBytes": int(memory.get("swapTotalBytes", 0)),
            "swapPercent": float(memory.get("swapPercent", 0.0)),
            "storagePercent": storage_percent,
            "storageUsedBytes": storage_used,
            "storageTotalBytes": storage_total,
            "networkRxBytesPerSec": int(network.get("rxBytesPerSec", 0)),
            "networkTxBytesPerSec": int(network.get("txBytesPerSec", 0)),
        },
        "lastSeen": record.get("lastSeen"),
        "stale": (now_ts - record["lastSeenTs"]) > HEARTBEAT_TTL_SECONDS,
    }


def node_capabilities(node_id):
    with _agent_nodes_lock:
        record = _agent_nodes.get(node_id)
        if not record:
            return []
        snap = record.get("snapshot", {})
        caps = snap.get("capabilities") or snap.get("node", {}).get("capabilities") or {}
        return caps.get("actions") or []


def action_allowed(node_id, action_id):
    if action_id == "agent.self_update":
        return True
    return any(item.get("id") == action_id for item in node_capabilities(node_id))


def queue_action(node_id, action_id, target=None, params=None, requested_by="web-ui"):
    request_id = f"act-{int(time.time() * 1000)}"
    entry = {
        "requestId": request_id,
        "nodeId": node_id,
        "actionId": action_id,
        "target": target,
        "params": params or {},
        "requestedBy": requested_by,
        "queuedAt": now_iso_utc(),
        "status": "queued",
    }
    with _action_lock:
        _action_queue.setdefault(node_id, []).append(entry)
        _action_log.append(dict(entry))
        if len(_action_log) > 500:
            _action_log[:] = _action_log[-500:]
    save_action_state()
    return entry


def pop_pending_actions(node_id, limit=5):
    with _action_lock:
        pending = _action_queue.get(node_id, [])
        if not pending:
            return []
        batch = pending[:limit]
        _action_queue[node_id] = pending[limit:]
        delivered_at = now_iso_utc()
        for item in batch:
            request_id = item.get("requestId")
            for log_item in reversed(_action_log):
                if log_item.get("requestId") == request_id and log_item.get("nodeId") == node_id:
                    log_item["status"] = "delivered"
                    log_item["deliveredAt"] = delivered_at
                    break
    save_action_state()
    return batch


def mark_action_result(node_id, request_id, ok, message):
    with _action_lock:
        for item in reversed(_action_log):
            if item.get("requestId") == request_id and item.get("nodeId") == node_id:
                item["status"] = "completed" if ok else "failed"
                item["completedAt"] = now_iso_utc()
                item["message"] = message
                break
    save_action_state()


def admin_agent_update_log(limit=50, node_id=""):
    with _action_lock:
        items = [
            item
            for item in _action_log
            if item.get("actionId") == "agent.self_update"
            and (not node_id or item.get("nodeId") == node_id)
        ]
        pending = {
            node: [
                item
                for item in entries
                if item.get("actionId") == "agent.self_update"
            ]
            for node, entries in _action_queue.items()
            if any(item.get("actionId") == "agent.self_update" for item in entries)
        }
    return {"items": items[-limit:], "pendingByNode": pending}


def summary_history_point(summary, at):
    resources = summary.get("resources", {})
    return {
        "at": at,
        "cpuPercent": resources.get("cpuPercent", 0.0),
        "memoryPercent": resources.get("memoryPercent", 0.0),
        "storagePercent": resources.get("storagePercent", 0.0),
        "networkRxBytesPerSec": resources.get("networkRxBytesPerSec", 0),
        "networkTxBytesPerSec": resources.get("networkTxBytesPerSec", 0),
    }


def run(command, timeout=1.5):
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout,
            check=False,
        )
        return result.returncode, result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 127, ""


def read_cpu_snapshot():
    with open("/proc/stat", "r", encoding="utf-8") as fh:
        parts = fh.readline().split()[1:]
    vals = [int(part) for part in parts]
    idle = vals[3] + vals[4]
    total = sum(vals)
    return idle, total


def cpu_percent():
    global _last_cpu
    current = read_cpu_snapshot()
    if _last_cpu is None:
        _last_cpu = current
        return 0.0
    idle_delta = current[0] - _last_cpu[0]
    total_delta = current[1] - _last_cpu[1]
    _last_cpu = current
    if total_delta <= 0:
        return 0.0
    return max(0.0, min(100.0, 100.0 * (1 - idle_delta / total_delta)))


def mem_stats():
    data = {}
    with open("/proc/meminfo", "r", encoding="utf-8") as fh:
        for line in fh:
            key, value = line.split(":", 1)
            data[key] = int(value.strip().split()[0])
    total = max(1, data.get("MemTotal", 1) * 1024)
    available = data.get("MemAvailable", 0) * 1024
    used = max(0, total - available)
    return {
        "percent": round((used * 100) / total, 1),
        "usedBytes": used,
        "totalBytes": total,
    }


def uptime_seconds():
    with open("/proc/uptime", "r", encoding="utf-8") as fh:
        return int(float(fh.read().split()[0]))


def net_totals():
    rx = tx = 0
    with open("/proc/net/dev", "r", encoding="utf-8") as fh:
        for line in fh.readlines()[2:]:
            iface, values = line.split(":", 1)
            iface = iface.strip()
            if iface == "lo":
                continue
            parts = values.split()
            rx += int(parts[0])
            tx += int(parts[8])
    return rx, tx


def net_rates():
    global _last_net, _last_net_ts
    now = time.time()
    rx, tx = net_totals()
    if _last_net is None or _last_net_ts is None:
        _last_net = (rx, tx)
        _last_net_ts = now
        return {"rxBytesPerSec": 0, "txBytesPerSec": 0}
    elapsed = max(0.001, now - _last_net_ts)
    rates = {
        "rxBytesPerSec": max(0, int((rx - _last_net[0]) / elapsed)),
        "txBytesPerSec": max(0, int((tx - _last_net[1]) / elapsed)),
    }
    _last_net = (rx, tx)
    _last_net_ts = now
    return rates


def primary_ips():
    _, out = run(["hostname", "-I"])
    return out.split()[:3]


def service_state(name):
    code, state = run(["systemctl", "is-active", name])
    if code == 0 and state == "active":
        return "running"
    if state in ("activating", "reloading"):
        return "starting"
    return "stopped"


def docker_available():
    code, _ = run(["docker", "info"], timeout=3.0)
    return code == 0


def _parse_docker_bytes(value):
    raw = str(value or "").strip().upper().replace(" ", "")
    if not raw:
        return 0
    units = (
        ("TIB", 1024**4),
        ("GIB", 1024**3),
        ("MIB", 1024**2),
        ("KIB", 1024),
        ("TB", 1000**4),
        ("GB", 1000**3),
        ("MB", 1000**2),
        ("KB", 1000),
        ("B", 1),
    )
    for suffix, mult in units:
        if raw.endswith(suffix):
            try:
                return int(float(raw[: -len(suffix)]) * mult)
            except ValueError:
                return 0
    try:
        return int(float(raw))
    except ValueError:
        return 0


def _parse_mem_usage(text):
    parts = str(text or "").split("/", 1)
    used = _parse_docker_bytes(parts[0].strip()) if parts else 0
    limit = _parse_docker_bytes(parts[1].strip()) if len(parts) > 1 else 0
    return used, limit


def container_stats_map():
    code, out = run(
        [
            "docker",
            "stats",
            "--no-stream",
            "--format",
            "{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.NetIO}}\t{{.BlockIO}}",
        ],
        timeout=5.0,
    )
    stats = {}
    if code != 0:
        return stats
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        name, cpu, mem_usage, mem_pct = parts[0], parts[1], parts[2], parts[3]
        used, limit = _parse_mem_usage(mem_usage)
        try:
            cpu_val = float(str(cpu).replace("%", "").strip())
        except ValueError:
            cpu_val = 0.0
        try:
            mem_pct_val = float(str(mem_pct).replace("%", "").strip())
        except ValueError:
            mem_pct_val = 0.0
        stats[name] = {
            "cpuPercent": round(cpu_val, 1),
            "memoryUsedBytes": used,
            "memoryLimitBytes": limit,
            "memoryPercent": round(mem_pct_val, 1),
            "networkIo": parts[4] if len(parts) > 4 else "",
            "blockIo": parts[5] if len(parts) > 5 else "",
        }
    return stats


def container_states():
    code, out = run(
        ["docker", "ps", "-a", "--format", "{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.State}}"],
        timeout=3.0,
    )
    if code != 0:
        return []
    stats = container_stats_map()
    rows = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        cid, name, image, status_text, state = parts[:5]
        normalized = str(state or "").lower()
        if normalized == "running":
            status = "running"
        elif normalized in {"exited", "dead"}:
            status = "stopped"
        elif normalized in {"created", "paused", "restarting"}:
            status = normalized
        else:
            status = "running" if str(status_text).lower().startswith("up") else "stopped"
        row = {
            "id": cid[:12],
            "name": name,
            "image": image,
            "statusText": status_text,
            "status": status,
        }
        row.update(stats.get(name, {}))
        rows.append(row)
    return rows


def storage_rows():
    rows = []
    for path in STORAGE_PATHS:
        if not os.path.exists(path):
            continue
        usage = shutil.disk_usage(path)
        percent = round((usage.used * 100) / max(1, usage.total), 1)
        rows.append(
            {
                "path": path,
                "usedBytes": usage.used,
                "totalBytes": usage.total,
                "percent": percent,
            }
        )
    return rows


def service_rows():
    rows = []
    for name in SERVICES:
        rows.append({"name": name, "status": service_state(name)})
    return rows


def filtered_containers():
    all_rows = container_states()
    if not all_rows:
        return []
    if not CONTAINERS:
        return all_rows
    matched = []
    seen = set()
    for wanted in CONTAINERS:
        for row in all_rows:
            if wanted.lower() in row["name"].lower() and row["name"] not in seen:
                matched.append(row)
                seen.add(row["name"])
    return matched or all_rows


def local_payload():
    docker_ready = docker_available()
    containers = filtered_containers() if docker_ready else []
    return {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "refreshSeconds": REFRESH_SECONDS,
        "node": {
            "id": socket.gethostname(),
            "hostname": socket.gethostname(),
            "platform": "linux",
            "uptimeSec": uptime_seconds(),
            "ips": primary_ips(),
        },
        "system": {
            "cpuPercent": round(cpu_percent(), 1),
            "memory": mem_stats(),
            "network": net_rates(),
        },
        "storage": storage_rows(),
        "services": service_rows(),
        "containers": containers,
        "docker": {"available": docker_ready, "containerCount": len(containers)},
        "source": "core-local",
    }


PUBLIC_ROUTE = object()


class Handler(BaseHTTPRequestHandler):
    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return None
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return None

    def _request_origin(self):
        origin = self.headers.get("Origin")
        if origin:
            return origin
        referer = self.headers.get("Referer")
        if referer:
            parsed = urlparse(referer)
            if parsed.scheme and parsed.netloc:
                return f"{parsed.scheme}://{parsed.netloc}"
        return auth.WEB_ORIGIN

    def _cors_origin(self):
        return auth.cors_origin_for(self._request_origin())

    def _session_id(self):
        return auth.parse_session_cookie(self.headers.get("Cookie"))

    def _current_user(self):
        return auth.resolve_request_user(self._session_id())

    def _require_user(self, min_role):
        user = self._current_user()
        if not auth.AUTH_ENABLED:
            return user or auth.authenticate("", "")
        if not user:
            self._send_json(401, {"error": "authentication required"})
            return None
        if not auth.user_has_role(user, min_role):
            self._send_json(403, {"error": "insufficient permissions", "requiredRole": min_role})
            return None
        return user

    def _enforce_route_auth(self, method, path):
        required = auth.route_required_role(method, path)
        if required is None:
            if path == "/api/v1/auth/me":
                return self._current_user()
            return PUBLIC_ROUTE
        return self._require_user(required)

    def _send_json(self, code, body, extra_headers=None):
        raw = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", self._cors_origin())
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Vary", "Origin")
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(raw)

    def _fleet_nodes(self):
        now = time.time()
        with _agent_nodes_lock:
            rows = []
            for node_id, record in _agent_nodes.items():
                stale = (now - record["lastSeenTs"]) > HEARTBEAT_TTL_SECONDS
                rows.append(
                    {
                        "nodeId": node_id,
                        "agentId": record.get("agentId", "unknown"),
                        "lastSeen": record["lastSeen"],
                        "stale": stale,
                    }
                )
        rows.sort(key=lambda r: r["lastSeen"], reverse=True)
        return rows

    def _fleet_overview(self, physical_only):
        now = time.time()
        with _agent_nodes_lock:
            rows = [snapshot_node_summary(node_id, record, now) for node_id, record in _agent_nodes.items()]

        rows = [row for row in rows if not row["hardware"].get("isContainer")]

        if physical_only:
            rows = [row for row in rows if row["hardware"]["isPhysical"] and not row["hardware"]["isVirtualMachine"]]

        rows.sort(key=lambda r: (r["deviceCategory"], r["hostname"]))
        servers = [row for row in rows if row["deviceCategory"] == "server"]
        clients = [row for row in rows if row["deviceCategory"] == "client"]

        total_memory = sum(row["resources"]["memoryTotalBytes"] for row in rows)
        used_memory = sum(row["resources"]["memoryUsedBytes"] for row in rows)
        total_storage = sum(row["resources"]["storageTotalBytes"] for row in rows)
        used_storage = sum(row["resources"]["storageUsedBytes"] for row in rows)
        avg_cpu = round(sum(row["resources"]["cpuPercent"] for row in rows) / len(rows), 1) if rows else 0.0
        stale_count = sum(1 for row in rows if row["stale"])

        return {
            "generatedAt": now_iso_utc(),
            "physicalOnly": physical_only,
            "refreshSeconds": REFRESH_SECONDS,
            "totals": {
                "nodeCount": len(rows),
                "serverCount": len(servers),
                "clientCount": len(clients),
                "staleCount": stale_count,
                "avgCpuPercent": avg_cpu,
                "memoryUsedBytes": used_memory,
                "memoryTotalBytes": total_memory,
                "storageUsedBytes": used_storage,
                "storageTotalBytes": total_storage,
            },
            "groups": {
                "servers": servers,
                "clients": clients,
            },
            "items": rows,
        }

    def _fleet_vms(self):
        now = time.time()
        items = []
        hosts = []
        with _agent_nodes_lock:
            for node_id, record in _agent_nodes.items():
                stale = (now - record["lastSeenTs"]) > HEARTBEAT_TTL_SECONDS
                snap = record.get("snapshot", {})
                node = snap.get("node", {})
                workloads = snap.get("workloads") or {}
                if workloads.get("kind") != "proxmox":
                    continue
                vms = workloads.get("vms") or []
                caps = snap.get("capabilities") or node.get("capabilities") or {}
                hostname = node.get("hostname") or node_id
                host_role = caps.get("hostRole") or node.get("hostRole") or "proxmox"
                vm_actions = [action for action in (caps.get("actions") or []) if action.get("scope") == "vm"]
                hosts.append(
                    {
                        "nodeId": node_id,
                        "hostname": hostname,
                        "hostRole": host_role,
                        "stale": stale,
                        "lastSeen": record.get("lastSeen"),
                        "vmCount": len(vms),
                    }
                )
                for vm in vms:
                    items.append(
                        {
                            "nodeId": node_id,
                            "hostname": hostname,
                            "hostRole": host_role,
                            "hostStale": stale,
                            "actions": vm_actions,
                            **vm,
                        }
                    )

        items.sort(
            key=lambda item: (
                item.get("hostname") or "",
                int(item["id"]) if str(item.get("id", "")).isdigit() else 99999,
            )
        )
        hosts.sort(key=lambda item: item.get("hostname") or "")
        running = sum(1 for item in items if item.get("status") == "running")
        stopped = sum(1 for item in items if item.get("status") == "stopped")
        paused = sum(1 for item in items if item.get("status") == "paused")
        return {
            "generatedAt": now_iso_utc(),
            "refreshSeconds": REFRESH_SECONDS,
            "totals": {
                "vmCount": len(items),
                "runningCount": running,
                "stoppedCount": stopped,
                "pausedCount": paused,
                "hostCount": len(hosts),
                "staleHostCount": sum(1 for host in hosts if host["stale"]),
            },
            "hosts": hosts,
            "items": items,
        }

    def _fleet_containers(self):
        now = time.time()
        items = []
        hosts = []
        with _agent_nodes_lock:
            for node_id, record in _agent_nodes.items():
                stale = (now - record["lastSeenTs"]) > HEARTBEAT_TTL_SECONDS
                snap = record.get("snapshot", {})
                node = snap.get("node", {})
                if str(node.get("platform") or "linux").lower() != "linux":
                    continue
                docker_info = snap.get("docker") or {}
                containers = snap.get("containers") or []
                caps = snap.get("capabilities") or node.get("capabilities") or {}
                sections = caps.get("sections") or {}
                if docker_info.get("available") is True:
                    docker_ready = True
                elif containers:
                    docker_ready = True
                elif sections.get("containers"):
                    docker_ready = True
                else:
                    docker_ready = False
                if not docker_ready:
                    continue
                hostname = node.get("hostname") or node_id
                host_role = caps.get("hostRole") or node.get("hostRole") or "linux"
                container_actions = [
                    action for action in (caps.get("actions") or []) if action.get("scope") == "container"
                ]
                running_count = sum(1 for row in containers if row.get("status") == "running")
                hosts.append(
                    {
                        "nodeId": node_id,
                        "hostname": hostname,
                        "hostRole": host_role,
                        "stale": stale,
                        "lastSeen": record.get("lastSeen"),
                        "containerCount": len(containers),
                        "runningCount": running_count,
                        "dockerAvailable": docker_info.get("available", True),
                    }
                )
                for container in containers:
                    items.append(
                        {
                            "nodeId": node_id,
                            "hostname": hostname,
                            "hostRole": host_role,
                            "hostStale": stale,
                            "actions": container_actions,
                            **container,
                        }
                    )

        items.sort(key=lambda item: (item.get("hostname") or "", item.get("name") or ""))
        hosts.sort(key=lambda item: item.get("hostname") or "")
        running = sum(1 for item in items if item.get("status") == "running")
        stopped = sum(1 for item in items if item.get("status") == "stopped")
        return {
            "generatedAt": now_iso_utc(),
            "refreshSeconds": REFRESH_SECONDS,
            "totals": {
                "containerCount": len(items),
                "runningCount": running,
                "stoppedCount": stopped,
                "hostCount": len(hosts),
                "staleHostCount": sum(1 for host in hosts if host["stale"]),
            },
            "hosts": hosts,
            "items": items,
        }

    def _fleet_services(self):
        now = time.time()
        items = []
        hosts = []
        with _agent_nodes_lock:
            for node_id, record in _agent_nodes.items():
                stale = (now - record["lastSeenTs"]) > HEARTBEAT_TTL_SECONDS
                snap = record.get("snapshot", {})
                node = snap.get("node", {})
                services = snap.get("services") or []
                if not services:
                    continue
                caps = snap.get("capabilities") or node.get("capabilities") or {}
                hostname = node.get("hostname") or node_id
                host_role = caps.get("hostRole") or node.get("hostRole") or "unknown"
                platform = str(node.get("platform") or "unknown").lower()
                service_actions = [
                    action for action in (caps.get("actions") or []) if action.get("scope") == "service"
                ]
                running_count = sum(1 for row in services if row.get("status") == "running")
                hosts.append(
                    {
                        "nodeId": node_id,
                        "hostname": hostname,
                        "hostRole": host_role,
                        "platform": platform,
                        "stale": stale,
                        "lastSeen": record.get("lastSeen"),
                        "serviceCount": len(services),
                        "runningCount": running_count,
                    }
                )
                for service in services:
                    items.append(
                        {
                            "nodeId": node_id,
                            "hostname": hostname,
                            "hostRole": host_role,
                            "platform": platform,
                            "hostStale": stale,
                            "actions": service_actions,
                            **service,
                        }
                    )

        items.sort(key=lambda item: (item.get("name") or "", item.get("hostname") or ""))
        hosts.sort(key=lambda item: item.get("hostname") or "")
        running = sum(1 for item in items if item.get("status") == "running")
        stopped = sum(1 for item in items if item.get("status") == "stopped")
        return {
            "generatedAt": now_iso_utc(),
            "refreshSeconds": REFRESH_SECONDS,
            "totals": {
                "serviceCount": len(items),
                "runningCount": running,
                "stoppedCount": stopped,
                "hostCount": len(hosts),
                "staleHostCount": sum(1 for host in hosts if host["stale"]),
            },
            "hosts": hosts,
            "items": items,
        }

    def _node_detail(self, node_id):
        now = time.time()
        with _agent_nodes_lock:
            record = _agent_nodes.get(node_id)
            if record is None:
                return None
            snap = json.loads(json.dumps(record.get("snapshot", {})))
            summary = snapshot_node_summary(node_id, record, now)
        return {
            "generatedAt": now_iso_utc(),
            "refreshSeconds": REFRESH_SECONDS,
            "nodeId": node_id,
            "summary": summary,
            "snapshot": snap,
        }

    def _node_history(self, node_id, limit):
        with _agent_nodes_lock:
            record = _agent_nodes.get(node_id)
            if record is None:
                return None
            history = record.get("history", [])
            if limit > 0:
                history = history[-limit:]
            return {
                "nodeId": node_id,
                "refreshSeconds": REFRESH_SECONDS,
                "items": history,
            }

    def _latest_agent_snapshot(self):
        with _agent_nodes_lock:
            if not _agent_nodes:
                return None
            latest = max(_agent_nodes.values(), key=lambda r: r["lastSeenTs"])
            return latest["snapshot"]

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path == "/healthz":
            self._send_json(200, {"ok": True, "auth": auth.auth_status()})
            return

        if path == "/api/v1/auth/me":
            user = self._require_user("observer")
            if not user:
                return
            self._send_json(200, {"authenticated": True, "user": user, "auth": auth.auth_status()})
            return

        auth_result = self._enforce_route_auth("GET", path)
        if auth_result is None:
            return
        # PUBLIC_ROUTE: read-only glance endpoints (login wallboard / kiosk)
        if path == "/api/v1/fleet/nodes":
            self._send_json(200, {"items": self._fleet_nodes()})
            return
        if path == "/api/v1/fleet/overview":
            physical_only = qs.get("physicalOnly", ["true"])[0].lower() != "false"
            self._send_json(200, self._fleet_overview(physical_only))
            return
        if path == "/api/v1/fleet/vms":
            self._send_json(200, self._fleet_vms())
            return
        if path == "/api/v1/fleet/containers":
            self._send_json(200, self._fleet_containers())
            return
        if path == "/api/v1/fleet/services":
            self._send_json(200, self._fleet_services())
            return
        if path == "/api/v1/fleet/node":
            node_id = qs.get("nodeId", [""])[0]
            if not node_id:
                self._send_json(400, {"error": "missing nodeId"})
                return
            detail = self._node_detail(node_id)
            if detail is None:
                self._send_json(404, {"error": "node not found"})
                return
            self._send_json(200, detail)
            return
        if path == "/api/v1/fleet/node/history":
            node_id = qs.get("nodeId", [""])[0]
            if not node_id:
                self._send_json(400, {"error": "missing nodeId"})
                return
            limit_raw = qs.get("limit", ["120"])[0]
            try:
                limit = max(1, min(1000, int(limit_raw)))
            except ValueError:
                limit = 120
            history = self._node_history(node_id, limit)
            if history is None:
                self._send_json(404, {"error": "node not found"})
                return
            self._send_json(200, history)
            return
        if path == "/api/v1/actions/log":
            node_id = qs.get("nodeId", [""])[0]
            action_id = qs.get("actionId", [""])[0]
            limit_raw = qs.get("limit", ["50"])[0]
            try:
                limit = max(1, min(200, int(limit_raw)))
            except ValueError:
                limit = 50
            with _action_lock:
                items = [
                    item
                    for item in _action_log
                    if (not node_id or item.get("nodeId") == node_id)
                    and (not action_id or item.get("actionId") == action_id)
                ]
            self._send_json(200, {"items": items[-limit:]})
            return
        if path == "/api/v1/admin/agent-updates/log":
            node_id = qs.get("nodeId", [""])[0]
            limit_raw = qs.get("limit", ["50"])[0]
            try:
                limit = max(1, min(200, int(limit_raw)))
            except ValueError:
                limit = 50
            self._send_json(200, admin_agent_update_log(limit=limit, node_id=node_id))
            return
        if path == "/api/v1/admin/agent-releases":
            self._send_json(
                200,
                {
                    "generatedAt": now_iso_utc(),
                    "webBaseUrl": load_agent_releases().get("webBaseUrl") or WEB_BASE_URL,
                    "platforms": admin_release_summary(),
                },
            )
            return
        if path == "/api/v1/admin/agent-inventory":
            self._send_json(
                200,
                {
                    "generatedAt": now_iso_utc(),
                    "items": admin_agent_inventory(),
                },
            )
            return
        if path == "/api/v1/fleet/node/capabilities":
            node_id = qs.get("nodeId", [""])[0]
            if not node_id:
                self._send_json(400, {"error": "missing nodeId"})
                return
            actions = node_capabilities(node_id)
            if not actions:
                self._send_json(404, {"error": "node not found or no capabilities"})
                return
            self._send_json(200, {"nodeId": node_id, "actions": actions})
            return
        if path == "/api/v1/integrations/security":
            self._send_json(200, integrations.security_integrations(refresh_seconds=60))
            return
        if path == "/api/v1/integrations/weather":
            self._send_json(200, integrations.weather_forecast())
            return
        if path == "/api/v1/integrations/climate":
            self._send_json(200, integrations.climate_integrations())
            return
        if path == "/api/v1/integrations/network":
            self._send_json(200, integrations.network_integrations(refresh_seconds=60))
            return
        if path == "/api/v1/system/version":
            self._send_json(200, branding.product_info(hcc_version()))
            return
        if path.startswith(integrations.FRIGATE_CAMERA_PATH_PREFIX) and path.endswith("/latest.jpg"):
            camera_name = path[len(integrations.FRIGATE_CAMERA_PATH_PREFIX) : -len("/latest.jpg")]
            if not camera_name:
                self._send_json(400, {"error": "missing camera name"})
                return
            try:
                body, content_type = integrations.fetch_frigate_camera_latest(camera_name)
            except ValueError:
                self._send_json(400, {"error": "invalid camera name"})
                return
            except Exception as exc:
                self._send_json(502, {"error": f"camera preview failed: {exc}"})
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", self._cors_origin())
            self.send_header("Access-Control-Allow-Credentials", "true")
            self.send_header("Vary", "Origin")
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/v1/dashboard/overview":
            snapshot = self._latest_agent_snapshot()
            if snapshot is None:
                body = local_payload()
                body["fleet"] = {"nodeCount": 1, "staleCount": 0}
                self._send_json(200, body)
                return
            fleet = self._fleet_nodes()
            stale_count = sum(1 for n in fleet if n["stale"])
            snapshot = json.loads(json.dumps(snapshot))
            snapshot["generatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            snapshot["refreshSeconds"] = REFRESH_SECONDS
            snapshot["fleet"] = {"nodeCount": len(fleet), "staleCount": stale_count}
            snapshot["source"] = "agent-heartbeat"
            self._send_json(200, snapshot)
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        body = self._read_json()
        if path != "/api/v1/agent/heartbeat" and not isinstance(body, dict):
            self._send_json(400, {"error": "invalid json"})
            return
        body = body if isinstance(body, dict) else {}

        if path == "/api/v1/auth/login":
            username = str(body.get("username") or "")
            password = str(body.get("password") or "")
            try:
                user, reason = auth.authenticate_with_reason(username, password)
            except Exception as exc:
                logger.exception("login error for %s: %s", username, exc)
                self._send_json(500, {"error": "Login failed due to a server error."})
                return
            if not user:
                message = auth.login_error_message(reason)
                logger.info("login failed for %s: %s", username, reason or "unknown")
                self._send_json(
                    401,
                    {
                        "error": message,
                        "reason": reason or "unknown",
                    },
                )
                return
            session_id = auth.create_session(user)
            self._send_json(
                200,
                {"ok": True, "user": user, "auth": auth.auth_status()},
                extra_headers={"Set-Cookie": auth.cookie_header(session_id)},
            )
            return

        if path == "/api/v1/auth/logout":
            auth.destroy_session(self._session_id())
            self._send_json(200, {"ok": True}, extra_headers={"Set-Cookie": auth.clear_cookie_header()})
            return

        auth_result = self._enforce_route_auth("POST", path)
        if auth_result is None:
            return
        user = None if auth_result is PUBLIC_ROUTE else auth_result

        if path == "/api/v1/actions/execute":
            node_id = str(body.get("nodeId") or "")
            action_id = str(body.get("actionId") or "")
            target = body.get("target")
            params = body.get("params") if isinstance(body.get("params"), dict) else {}
            requested_by = user.get("principal") if user else "web-ui"
            if not node_id or not action_id:
                self._send_json(400, {"error": "missing nodeId or actionId"})
                return
            if not auth.user_may_execute_action(user, action_id):
                self._send_json(
                    403,
                    {
                        "error": "action not permitted for user role",
                        "requiredRole": auth.action_required_role(action_id),
                    },
                )
                return
            if not action_allowed(node_id, action_id):
                self._send_json(403, {"error": "action not allowed for node"})
                return
            entry = queue_action(node_id, action_id, target=target, params=params, requested_by=requested_by)
            self._send_json(202, entry)
            return

        if path == "/api/v1/admin/agent-updates/push":
            result = push_agent_updates(
                body,
                requested_by=user.get("principal") if user else "admin-ui",
            )
            self._send_json(202, result)
            return

        if path == "/api/v1/integrations/climate/set":
            if not auth.user_has_role(user, "operator"):
                self._send_json(403, {"error": "operator role required for climate controls"})
                return
            entity_id = str(body.get("entityId") or "")
            try:
                result = integrations.set_climate_control(
                    entity_id,
                    hvac_mode=body.get("hvacMode"),
                    temperature=body.get("temperature"),
                    fan_mode=body.get("fanMode"),
                    target_temp_high=body.get("targetTempHigh"),
                    target_temp_low=body.get("targetTempLow"),
                )
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
                return
            except Exception as exc:
                self._send_json(502, {"error": f"climate control failed: {exc}"})
                return
            self._send_json(200, result)
            return

        if path == "/api/v1/agent/action-result":
            node_id = str(body.get("nodeId") or "")
            request_id = str(body.get("requestId") or "")
            ok = bool(body.get("ok"))
            message = str(body.get("message") or "")
            if not node_id or not request_id:
                self._send_json(400, {"error": "missing nodeId or requestId"})
                return
            mark_action_result(node_id, request_id, ok, message)
            self._send_json(200, {"ok": True})
            return

        if path != "/api/v1/agent/heartbeat":
            self._send_json(404, {"error": "not found"})
            return

        snapshot = body.get("payload")
        if not isinstance(snapshot, dict):
            self._send_json(400, {"error": "missing payload object"})
            return

        node = snapshot.get("node", {})
        node_id = str(body.get("nodeId") or node.get("id") or node.get("hostname") or "")
        if not node_id:
            self._send_json(400, {"error": "missing node id"})
            return

        for result in body.get("actionResults") or []:
            if isinstance(result, dict) and result.get("requestId"):
                mark_action_result(
                    node_id,
                    str(result.get("requestId")),
                    bool(result.get("ok")),
                    str(result.get("message") or ""),
                )

        now_ts = time.time()
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now_ts))
        try:
            base_record = {
                "agentId": str(body.get("agentId") or "agent-unknown"),
                "agentVersion": str(
                    body.get("agentVersion")
                    or node.get("agentVersion")
                    or "unknown"
                ),
                "lastSeenTs": now_ts,
                "lastSeen": now_iso,
                "snapshot": json.loads(json.dumps(snapshot)),
            }
            summary = snapshot_node_summary(node_id, base_record, now_ts)
            point = summary_history_point(summary, now_iso)
            with _agent_nodes_lock:
                existing = _agent_nodes.get(node_id)
                history = existing.get("history", []) if isinstance(existing, dict) else []
                history.append(point)
                if len(history) > NODE_HISTORY_LIMIT:
                    history = history[-NODE_HISTORY_LIMIT:]
                base_record["history"] = history
                _agent_nodes[node_id] = base_record
            save_fleet_state()
            pending = pop_pending_actions(node_id)
            self._send_json(202, {"ok": True, "nodeId": node_id, "acceptedAt": now_iso, "pendingActions": pending})
        except Exception as exc:
            self._send_json(500, {"error": "heartbeat processing failed", "detail": str(exc)})

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", self._cors_origin())
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Vary", "Origin")
        self.end_headers()
        return


def main():
    load_fleet_state()
    load_action_state()
    status = auth.auth_status()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"hcc-core listening on {HOST}:{PORT}")
    print(f"hcc-core auth enabled={status['enabled']} ldap={status['ldapConfigured']} localAdmin={status['localAdminConfigured']}")
    server.serve_forever()


if __name__ == "__main__":
    main()

