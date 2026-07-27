#!/usr/bin/env python3
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

from action_runner import execute_action
from host_intelligence import detect_host_role, host_extensions


CORE_BASE_URL = os.environ.get("HCC_CORE_BASE_URL", "").strip().rstrip("/")
CORE_URL = os.environ.get("HCC_CORE_HEARTBEAT_URL", "").strip()
if not CORE_URL and CORE_BASE_URL:
    CORE_URL = f"{CORE_BASE_URL}/api/v1/agent/heartbeat"
INTERVAL_SECONDS = float(os.environ.get("HCC_AGENT_INTERVAL_SECONDS", "120"))
NODE_ID = os.environ.get("HCC_AGENT_NODE_ID", socket.gethostname())
AGENT_ID = os.environ.get("HCC_AGENT_ID", f"agent-{NODE_ID}")
AGENT_VERSION = os.environ.get("HCC_AGENT_VERSION", "1.0.5").strip() or "1.0.5"
INSTALL_DIR = os.environ.get("HCC_AGENT_INSTALL_DIR", "/opt/hcc-agent")
ENV_PATH = os.environ.get("HCC_AGENT_ENV_PATH", "/etc/hcc-agent.env")
STATE_DIR = os.environ.get("HCC_AGENT_STATE_DIR", "/var/lib/hcc-agent")
LOG_PATH = os.path.join(STATE_DIR, "agent.log")
STATE_PATH = os.path.join(STATE_DIR, "agent-state.json")
SERVICES = [s.strip() for s in os.environ.get("HCC_SERVICES", "docker,ssh,ufw").split(",") if s.strip()]
CONTAINERS = [c.strip() for c in os.environ.get("HCC_CONTAINERS", "nextcloud,jellyfin,mariadb,postgres,redis,nginx,traefik,caddy").split(",") if c.strip()]
STORAGE_PATHS = [p.strip() for p in os.environ.get("HCC_STORAGE_PATHS", "/,/srv,/mnt/storage,/media/storage").split(",") if p.strip()]

PSEUDO_FSTYPES = {
    "proc", "sysfs", "devtmpfs", "tmpfs", "devpts", "cgroup", "cgroup2",
    "pstore", "securityfs", "debugfs", "tracefs", "configfs", "fusectl",
    "mqueue", "hugetlbfs", "binfmt_misc", "autofs", "rpc_pipefs",
}

_last_cpu = None
_last_net = None
_last_net_ts = None


def ensure_state_dir():
    os.makedirs(STATE_DIR, mode=0o750, exist_ok=True)


def write_agent_log(message):
    try:
        ensure_state_dir()
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(f"{stamp} {message}\n")
    except OSError:
        pass


def read_agent_state():
    if not os.path.exists(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def write_agent_state(success, message="", consecutive_failures=0):
    previous = read_agent_state()
    attempt_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    state = {
        "lastAttemptUtc": attempt_utc,
        "consecutiveFailures": consecutive_failures,
        "lastMessage": message,
    }
    if success:
        state["lastSuccessUtc"] = attempt_utc
    elif previous.get("lastSuccessUtc"):
        state["lastSuccessUtc"] = previous["lastSuccessUtc"]
    try:
        ensure_state_dir()
        with open(STATE_PATH, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
    except OSError:
        pass


def retry_delay_seconds(failures, normal_interval):
    if failures <= 0:
        return normal_interval
    delay = int(15 * (2 ** min(failures - 1, 3)))
    return max(15, min(int(normal_interval), delay))


def transient_web_error(message):
    if not message:
        return False
    lowered = message.lower()
    needles = (
        "unable to connect",
        "timed out",
        "temporarily unavailable",
        "connection refused",
        "connection reset",
        "name or service not known",
        "network is unreachable",
        "bad gateway",
        "service unavailable",
        "gateway timeout",
    )
    return any(needle in lowered for needle in needles)


def read_os_release():
    data = {}
    try:
        with open("/etc/os-release", "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                data[key] = value.strip('"')
    except FileNotFoundError:
        return {}
    return data


def virtualization_type():
    code, out = run(["systemd-detect-virt"])
    if code != 0:
        return "unknown"
    virt = (out or "").strip().lower()
    return virt or "unknown"


def cgroup_container_hint():
    try:
        with open("/proc/1/cgroup", "r", encoding="utf-8") as fh:
            raw = fh.read().lower()
    except FileNotFoundError:
        return False
    return any(token in raw for token in ("docker", "containerd", "kubepods", "podman", "lxc"))


def dockerenv_hint():
    return os.path.exists("/.dockerenv")


def hardware_profile():
    virt = virtualization_type()
    is_vm = virt in {"kvm", "qemu", "vmware", "xen", "microsoft", "oracle", "bochs", "uml", "parallels", "bhyve", "hyperv"}
    is_container = virt in {"docker", "podman", "lxc", "lxc-libvirt", "openvz", "wsl", "systemd-nspawn"} or cgroup_container_hint() or dockerenv_hint()
    is_physical = virt == "none" or (virt == "unknown" and not is_vm and not is_container)
    return {
        "virtualizationType": virt,
        "isVirtualMachine": is_vm,
        "isContainer": is_container,
        "isPhysical": is_physical,
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
    swap_total = data.get("SwapTotal", 0) * 1024
    swap_free = data.get("SwapFree", 0) * 1024
    swap_used = max(0, swap_total - swap_free)
    return {
        "percent": round((used * 100) / total, 1),
        "usedBytes": used,
        "totalBytes": total,
        "availableBytes": available,
        "swapUsedBytes": swap_used,
        "swapTotalBytes": swap_total,
        "swapPercent": round((swap_used * 100) / max(1, swap_total), 1) if swap_total else 0.0,
    }


def load_average():
    try:
        one, five, fifteen = os.getloadavg()
        return {
            "load1": round(one, 2),
            "load5": round(five, 2),
            "load15": round(fifteen, 2),
        }
    except OSError:
        return {"load1": 0.0, "load5": 0.0, "load15": 0.0}


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


def uptime_seconds():
    with open("/proc/uptime", "r", encoding="utf-8") as fh:
        return int(float(fh.read().split()[0]))


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


def usage_row(path, source=None, fstype=None, kind="mount"):
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return None
    return {
        "path": path,
        "source": source or path,
        "fstype": fstype or "unknown",
        "kind": kind,
        "usedBytes": usage.used,
        "totalBytes": usage.total,
        "freeBytes": max(0, usage.total - usage.used),
        "percent": round((usage.used * 100) / max(1, usage.total), 1),
    }


def storage_rows():
    rows = []
    seen = set()
    for path in STORAGE_PATHS:
        if not os.path.exists(path):
            continue
        item = usage_row(path, source=path, fstype="configured", kind="configured")
        if item:
            rows.append(item)
            seen.add(path)
    return rows


def zfs_pools():
    code, out = run(["zpool", "list", "-Hp", "-o", "name,size,alloc,free,cap,health"], timeout=3.0)
    if code != 0 or not out:
        return []
    rows = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 6:
            continue
        name, size, alloc, free, cap, health = parts[:6]
        try:
            total = int(size)
            used = int(alloc)
            free_bytes = int(free)
            percent = round(float(cap), 1)
        except ValueError:
            continue
        rows.append(
            {
                "name": name,
                "path": name,
                "source": name,
                "fstype": "zfs",
                "kind": "zfs-pool",
                "health": health,
                "usedBytes": used,
                "totalBytes": total,
                "freeBytes": free_bytes,
                "percent": percent,
            }
        )
    return rows


def zfs_datasets():
    code, out = run(
        ["zfs", "list", "-Hp", "-o", "name,used,avail,refer,mountpoint,type"],
        timeout=4.0,
    )
    if code != 0 or not out:
        return []
    rows = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 6:
            continue
        name, used, avail, refer, mountpoint, ds_type = parts[:6]
        if ds_type not in {"filesystem", "volume"}:
            continue
        if mountpoint in {"none", "-", "legacy"}:
            continue
        try:
            used_bytes = int(used)
            avail_bytes = int(avail)
            total = max(1, used_bytes + avail_bytes)
        except ValueError:
            continue
        rows.append(
            {
                "name": name,
                "path": mountpoint,
                "source": name,
                "fstype": "zfs",
                "kind": "zfs-dataset",
                "usedBytes": used_bytes,
                "totalBytes": total,
                "freeBytes": avail_bytes,
                "percent": round((used_bytes * 100) / total, 1),
            }
        )
    return rows


def mounted_filesystems():
    rows = []
    seen = set()
    try:
        with open("/proc/mounts", "r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except FileNotFoundError:
        return rows

    for line in lines:
        parts = line.split()
        if len(parts) < 3:
            continue
        source, mountpoint, fstype = parts[0], parts[1], parts[2]
        if fstype in PSEUDO_FSTYPES:
            continue
        if mountpoint in seen:
            continue
        if not os.path.isdir(mountpoint):
            continue
        item = usage_row(mountpoint, source=source, fstype=fstype, kind="mount")
        if not item:
            continue
        seen.add(mountpoint)
        rows.append(item)
    rows.sort(key=lambda r: r["path"])
    return rows


def block_devices():
    code, out = run(["lsblk", "-b", "-J", "-o", "NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,MODEL"], timeout=3.0)
    if code != 0 or not out:
        return []
    try:
        payload = json.loads(out)
    except json.JSONDecodeError:
        return []

    rows = []

    def walk(node, parent=None):
        name = node.get("name", "")
        full_name = f"{parent}/{name}" if parent else name
        size = int(node.get("size") or 0)
        dev_type = node.get("type") or "unknown"
        if dev_type in {"disk", "part", "lvm", "raid"} and size > 0:
            rows.append(
                {
                    "name": full_name,
                    "path": full_name,
                    "source": node.get("model") or full_name,
                    "fstype": node.get("fstype") or "-",
                    "kind": dev_type,
                    "mountpoint": node.get("mountpoint") or "-",
                    "usedBytes": 0,
                    "totalBytes": size,
                    "freeBytes": size,
                    "percent": 0.0,
                }
            )
        for child in node.get("children") or []:
            walk(child, full_name)

    for device in payload.get("blockdevices") or []:
        walk(device)
    return rows


def storage_totals(*groups):
    total = used = 0
    for group in groups:
        for item in group:
            total += int(item.get("totalBytes") or 0)
            used += int(item.get("usedBytes") or 0)
    if total <= 0:
        return {"usedBytes": 0, "totalBytes": 0, "freeBytes": 0, "percent": 0.0}
    return {
        "usedBytes": used,
        "totalBytes": total,
        "freeBytes": max(0, total - used),
        "percent": round((used * 100) / total, 1),
    }


def storage_detail():
    configured = storage_rows()
    zfs_pool_rows = zfs_pools()
    zfs_dataset_rows = zfs_datasets()
    mounts = mounted_filesystems()
    block = block_devices()
    hardware = hardware_profile()

    totals_source = zfs_pool_rows if zfs_pool_rows else mounts if mounts else configured
    totals = storage_totals(totals_source)

    return {
        "totals": totals,
        "configuredPaths": configured,
        "zfsPools": zfs_pool_rows,
        "zfsDatasets": zfs_dataset_rows[:24],
        "filesystems": mounts,
        "blockDevices": block if hardware.get("isPhysical") else block[:12],
    }


def normalize_service_name(name):
    value = str(name or "").strip()
    if value.endswith(".service"):
        return value[:-8]
    return value


def controlled_service_names():
    return {normalize_service_name(name).lower() for name in SERVICES if name}


def service_rows():
    controlled = controlled_service_names()
    code, out = run(
        ["systemctl", "list-units", "--type=service", "--all", "--no-pager", "--no-legend", "--plain"],
        timeout=45,
    )
    rows = []
    seen = set()
    if code == 0 and out:
        for line in out.splitlines():
            parts = line.split(None, 4)
            if len(parts) < 4:
                continue
            unit = parts[0]
            if not unit.endswith(".service"):
                continue
            name = normalize_service_name(unit)
            active = parts[2].lower()
            sub = parts[3].lower()
            if active == "active":
                status = "running"
            elif sub in ("activating", "reloading") or active == "activating":
                status = "starting"
            else:
                status = "stopped"
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            rows.append({"name": name, "status": status, "managed": key in controlled})
    if not rows:
        for name in SERVICES:
            key = normalize_service_name(name).lower()
            rows.append({"name": name, "status": service_state(name), "managed": True})
    rows.sort(key=lambda item: item["name"].lower())
    return rows


def make_snapshot():
    os_release = read_os_release()
    hardware = hardware_profile()
    host_role = detect_host_role(hardware)
    docker_ready = docker_available()
    extensions = host_extensions(host_role, hardware, docker_ready=docker_ready)
    storage = storage_detail()
    containers = filtered_containers() if docker_ready else []
    return {
        "node": {
            "id": NODE_ID,
            "hostname": socket.gethostname(),
            "platform": "linux",
            "hostRole": host_role,
            "deviceCategory": extensions["deviceCategory"],
            "agentVersion": AGENT_VERSION,
            "uptimeSec": uptime_seconds(),
            "ips": primary_ips(),
            "os": {
                "name": os_release.get("NAME") or platform.system(),
                "version": os_release.get("VERSION") or os_release.get("VERSION_ID") or platform.release(),
                "kernel": platform.release(),
                "arch": platform.machine(),
            },
            "hardware": hardware,
            "cpu": extensions["cpu"],
        },
        "capabilities": extensions["capabilities"],
        "workloads": extensions["workloads"],
        "system": {
            "cpuPercent": round(cpu_percent(), 1),
            "cpu": load_average(),
            "memory": mem_stats(),
            "network": net_rates(),
        },
        "storage": storage.get("configuredPaths") or storage_rows(),
        "storageDetail": storage,
        "services": service_rows() if host_role != "proxmox" else [],
        "containers": containers,
        "docker": {"available": docker_ready, "containerCount": len(containers)},
    }


def process_pending_actions(pending):
    results = []
    for action in pending or []:
        if not isinstance(action, dict):
            continue
        request_id = str(action.get("requestId") or "")
        action_id = str(action.get("actionId") or "")
        target = action.get("target")
        params = action.get("params") if isinstance(action.get("params"), dict) else {}
        code, message = execute_action(action_id, target=target, params=params)
        results.append(
            {
                "requestId": request_id,
                "actionId": action_id,
                "target": target,
                "ok": code == 0,
                "message": message,
            }
        )
    return results


def send_heartbeat(action_results=None):
    body = {
        "schemaVersion": "v1",
        "messageType": "heartbeat",
        "messageId": f"msg-{int(time.time() * 1000)}",
        "sentAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "agentId": AGENT_ID,
        "agentVersion": AGENT_VERSION,
        "nodeId": NODE_ID,
        "payload": make_snapshot(),
    }
    if action_results:
        body["actionResults"] = action_results
    payload = json.dumps(body).encode("utf-8")
    last_error = None
    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(
                CORE_URL,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=20) as response:
                raw = response.read().decode("utf-8")
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    return {}
        except Exception as exc:
            last_error = exc
            message = str(exc)
            if attempt < 3 and transient_web_error(message):
                time.sleep(5)
                continue
            raise
    if last_error:
        raise last_error
    return {}


def run_once():
    return "--once" in sys.argv


def main():
    if not CORE_URL:
        raise SystemExit(
            "Missing HCC_CORE_HEARTBEAT_URL or HCC_CORE_BASE_URL environment variable."
        )

    once = run_once()
    state = read_agent_state()
    consecutive_failures = int(state.get("consecutiveFailures") or 0)
    write_agent_log(f"hcc-agent starting for {NODE_ID} -> {CORE_URL} once={once}")
    print(f"hcc-agent sending heartbeat to {CORE_URL}")

    while True:
        try:
            response = send_heartbeat()
            pending = response.get("pendingActions") or []
            if pending:
                results = process_pending_actions(pending)
                send_heartbeat(action_results=results)
                message = f"processed {len(results)} action(s)"
            else:
                message = "heartbeat sent"
            consecutive_failures = 0
            write_agent_state(True, message, 0)
            write_agent_log(message)
            print(message)
        except Exception as exc:
            consecutive_failures += 1
            message = str(exc)
            write_agent_state(False, message, consecutive_failures)
            write_agent_log(f"heartbeat failed ({consecutive_failures}): {message}")
            print(f"heartbeat failed: {message}")

        if once:
            break

        sleep_seconds = retry_delay_seconds(consecutive_failures, INTERVAL_SECONDS)
        time.sleep(sleep_seconds)


if __name__ == "__main__":
    main()
