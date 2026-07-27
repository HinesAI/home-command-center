#!/usr/bin/env python3
import json
import os
import platform
import socket
import subprocess
import time
import urllib.request

from action_runner import execute_action
from host_intelligence import detect_host_role, host_extensions


DEFAULT_ENV_PATH = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "HCC-Agent", "hcc-agent.env")
LOG_PATH = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "HCC-Agent", "agent.log")

CORE_BASE_URL = os.environ.get("HCC_CORE_BASE_URL", "").strip().rstrip("/")
CORE_URL = os.environ.get("HCC_CORE_HEARTBEAT_URL", "").strip()
INTERVAL_SECONDS = float(os.environ.get("HCC_AGENT_INTERVAL_SECONDS", "120"))
NODE_ID = os.environ.get("HCC_AGENT_NODE_ID", socket.gethostname())
AGENT_ID = os.environ.get("HCC_AGENT_ID", f"agent-{NODE_ID}")
SERVICES = [
    s.strip()
    for s in os.environ.get("HCC_SERVICES", "W3SVC,DNS,DHCP,Spooler,WinRM").split(",")
    if s.strip()
]
STORAGE_DRIVES = [
    d.strip().upper()
    for d in os.environ.get("HCC_STORAGE_DRIVES", "C").split(",")
    if d.strip()
]

_last_cpu = None
_last_net = None
_last_net_ts = None


def agent_log(message):
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(f"{stamp} {message}\n")
    except OSError:
        pass


def load_env_file(path):
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"'))


def run_powershell(script, timeout=8.0):
    command = [
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        script,
    ]
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout,
            check=False,
        )
        return result.returncode, (result.stdout or "").strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 127, ""


def ps_json(script, timeout=8.0):
    wrapped = (
        "$ErrorActionPreference='SilentlyContinue'; "
        "try { "
        f"{script} | ConvertTo-Json -Compress -Depth 6 "
        "} catch { '' }"
    )
    code, out = run_powershell(wrapped, timeout=timeout)
    if code != 0 or not out:
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


def os_info():
    data = ps_json(
        """
        $os = Get-CimInstance Win32_OperatingSystem
        [pscustomobject]@{
            name = [string]$os.Caption
            version = [string]$os.Version
            build = [string]$os.BuildNumber
            arch = [string]$os.OSArchitecture
        }
        """
    )
    if not isinstance(data, dict):
        return {
            "name": platform.system(),
            "version": platform.version(),
            "kernel": platform.release(),
            "arch": platform.machine(),
        }
    return {
        "name": data.get("name") or "Windows",
        "version": data.get("version") or platform.version(),
        "kernel": data.get("build") or platform.release(),
        "arch": data.get("arch") or platform.machine(),
    }


def uptime_seconds():
    data = ps_json(
        """
        $os = Get-CimInstance Win32_OperatingSystem
        [int][math]::Max(0, ((Get-Date) - $os.LastBootUpTime).TotalSeconds)
        """
    )
    if isinstance(data, int):
        return data
    if isinstance(data, float):
        return int(data)
    return 0


def primary_ips():
    data = ps_json(
        """
        $ips = @()
        try {
            $ips = Get-NetIPAddress -AddressFamily IPv4 |
              Where-Object { $_.IPAddress -notlike '127.*' -and $_.PrefixOrigin -ne 'WellKnown' } |
              Select-Object -First 3 -ExpandProperty IPAddress
        } catch {}
        if (-not $ips) {
            $ips = Get-CimInstance Win32_NetworkAdapterConfiguration |
              Where-Object { $_.IPEnabled -eq $true -and $_.IPAddress } |
              ForEach-Object { $_.IPAddress } |
              Where-Object { $_ -notlike '127.*' } |
              Select-Object -First 3
        }
        $ips
        """
    )
    if isinstance(data, list):
        return [str(item) for item in data[:3]]
    if isinstance(data, str) and data:
        return [data]
    try:
        return [socket.gethostbyname(socket.gethostname())]
    except OSError:
        return []


def cpu_percent():
    global _last_cpu
    data = ps_json(
        """
        $sample = Get-CimInstance Win32_PerfFormattedData_PerfOS_Processor |
          Where-Object { $_.Name -eq '_Total' } |
          Select-Object -First 1
        [pscustomobject]@{
            idle = [double]$sample.PercentIdleTime
            queue = [double](Get-CimInstance Win32_PerfFormattedData_PerfOS_System).ProcessorQueueLength
        }
        """
    )
    if not isinstance(data, dict):
        return 0.0, 0.0
    idle = float(data.get("idle") or 100.0)
    queue = float(data.get("queue") or 0.0)
    used = max(0.0, min(100.0, 100.0 - idle))
    if _last_cpu is None:
        _last_cpu = used
        return used, queue
    smoothed = (_last_cpu + used) / 2.0
    _last_cpu = used
    return round(smoothed, 1), round(queue, 2)


def mem_stats():
    data = ps_json(
        """
        $os = Get-CimInstance Win32_OperatingSystem
        $total = [int64]$os.TotalVisibleMemorySize * 1024
        $free = [int64]$os.FreePhysicalMemory * 1024
        $used = [int64]($total - $free)
        $swapTotal = [int64]($os.TotalVirtualMemorySize - $os.TotalVisibleMemorySize) * 1024
        $swapFree = [int64]($os.FreeVirtualMemory - $os.FreePhysicalMemory) * 1024
        if ($swapFree -lt 0) { $swapFree = 0 }
        $swapUsed = [int64]($swapTotal - $swapFree)
        if ($swapUsed -lt 0) { $swapUsed = 0 }
        [pscustomobject]@{
            totalBytes = $total
            usedBytes = $used
            availableBytes = $free
            swapTotalBytes = $swapTotal
            swapUsedBytes = $swapUsed
        }
        """
    )
    if not isinstance(data, dict):
        return {
            "percent": 0.0,
            "usedBytes": 0,
            "totalBytes": 0,
            "availableBytes": 0,
            "swapUsedBytes": 0,
            "swapTotalBytes": 0,
            "swapPercent": 0.0,
        }
    total = max(1, int(data.get("totalBytes") or 1))
    used = max(0, int(data.get("usedBytes") or 0))
    swap_total = max(0, int(data.get("swapTotalBytes") or 0))
    swap_used = max(0, int(data.get("swapUsedBytes") or 0))
    return {
        "percent": round((used * 100) / total, 1),
        "usedBytes": used,
        "totalBytes": total,
        "availableBytes": int(data.get("availableBytes") or 0),
        "swapUsedBytes": swap_used,
        "swapTotalBytes": swap_total,
        "swapPercent": round((swap_used * 100) / max(1, swap_total), 1) if swap_total else 0.0,
    }


def net_totals():
    data = ps_json(
        """
        $rx = 0
        $tx = 0
        try {
            $stats = Get-NetAdapterStatistics | Where-Object { $_.Name -notlike 'Loopback*' }
            $rx = [int64](($stats | Measure-Object -Property ReceivedBytes -Sum).Sum)
            $tx = [int64](($stats | Measure-Object -Property SentBytes -Sum).Sum)
        } catch {}
        if ($rx -eq 0 -and $tx -eq 0) {
            $perf = Get-CimInstance Win32_PerfRawData_Tcpip_NetworkInterface -ErrorAction SilentlyContinue |
              Where-Object { $_.Name -notlike '*Loopback*' -and $_.Name -notlike '*isatap*' }
            $rx = [int64](($perf | Measure-Object -Property BytesReceivedPerSec -Sum).Sum)
            $tx = [int64](($perf | Measure-Object -Property BytesSentPerSec -Sum).Sum)
        }
        [pscustomobject]@{ rx = $rx; tx = $tx }
        """
    )
    if not isinstance(data, dict):
        return 0, 0
    return int(data.get("rx") or 0), int(data.get("tx") or 0)


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


def storage_rows():
    letters = ",".join(f"'{drive[:1]}'" for drive in STORAGE_DRIVES)
    data = ps_json(
        f"""
        Get-CimInstance Win32_LogicalDisk |
          Where-Object {{ $_.DriveType -eq 3 -and $_.DeviceID -in @({letters}) }} |
          ForEach-Object {{
            $total = [int64]$_.Size
            $free = [int64]$_.FreeSpace
            $used = [int64]($total - $free)
            [pscustomobject]@{{
                path = [string]$_.DeviceID
                source = [string]$_.DeviceID
                fstype = [string]$_.FileSystem
                kind = 'volume'
                usedBytes = $used
                totalBytes = $total
                freeBytes = $free
                percent = if ($total -gt 0) {{ [math]::Round(($used * 100.0) / $total, 1) }} else {{ 0 }}
            }}
          }}
        """
    )
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return []
    return data


def storage_detail():
    rows = storage_rows()
    used = sum(int(item.get("usedBytes", 0)) for item in rows)
    total = sum(int(item.get("totalBytes", 0)) for item in rows)
    percent = round((used * 100) / max(1, total), 1) if total else 0.0
    return {
        "totals": {
            "usedBytes": used,
            "totalBytes": total,
            "freeBytes": max(0, total - used),
            "percent": percent,
        },
        "configuredPaths": rows,
        "filesystems": rows,
        "blockDevices": [],
        "zfsPools": [],
        "zfsDatasets": [],
    }


def normalize_service_status(raw):
    value = str(raw or "").lower()
    if value in {"running", "start pending"}:
        return "running"
    if value in {"stopped", "stop pending"}:
        return "stopped"
    if "pause" in value:
        return "starting"
    return "stopped"


def service_rows():
    if not SERVICES:
        return []
    names = ",".join(f"'{name}'" for name in SERVICES)
    data = ps_json(
        f"""
        Get-Service -Name @({names}) -ErrorAction SilentlyContinue |
          ForEach-Object {{
            [pscustomobject]@{{
                name = [string]$_.Name
                status = [string]$_.Status
            }}
          }}
        """
    )
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return []
    return [{"name": row.get("name"), "status": normalize_service_status(row.get("status"))} for row in data]


def make_snapshot():
    from host_intelligence import hardware_profile

    hardware = hardware_profile()
    host_role = detect_host_role(hardware)
    extensions = host_extensions(host_role, hardware)
    storage = storage_detail()
    cpu_used, cpu_queue = cpu_percent()
    return {
        "node": {
            "id": NODE_ID,
            "hostname": socket.gethostname(),
            "platform": "windows",
            "hostRole": host_role,
            "deviceCategory": extensions["deviceCategory"],
            "uptimeSec": uptime_seconds(),
            "ips": primary_ips(),
            "os": os_info(),
            "hardware": hardware,
            "cpu": extensions["cpu"],
        },
        "capabilities": extensions["capabilities"],
        "workloads": extensions["workloads"],
        "system": {
            "cpuPercent": cpu_used,
            "cpu": {
                "load1": cpu_queue,
                "load5": 0.0,
                "load15": 0.0,
                "queueLength": cpu_queue,
            },
            "memory": mem_stats(),
            "network": net_rates(),
        },
        "storage": storage.get("configuredPaths") or storage_rows(),
        "storageDetail": storage,
        "services": service_rows(),
        "containers": [],
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
    try:
        payload = make_snapshot()
    except Exception as exc:
        agent_log(f"snapshot failed: {exc}")
        payload = {
            "node": {
                "id": NODE_ID,
                "hostname": socket.gethostname(),
                "platform": "windows",
                "hostRole": "windows-server",
                "deviceCategory": "server",
                "uptimeSec": 0,
                "ips": [],
                "os": os_info(),
                "hardware": {"virtualizationType": "unknown", "isPhysical": True, "isVirtualMachine": False, "isContainer": False},
                "cpu": {"model": "Unknown CPU", "logicalCpus": 0, "physicalCores": 0},
            },
            "capabilities": {"hostRole": "windows-server", "deviceCategory": "server", "actions": [], "sections": {"services": True, "storage": True}},
            "workloads": {"kind": "windows-server", "focus": ["storage"]},
            "system": {"cpuPercent": 0.0, "cpu": {"load1": 0.0}, "memory": mem_stats(), "network": {"rxBytesPerSec": 0, "txBytesPerSec": 0}},
            "storage": [],
            "storageDetail": {"totals": {"usedBytes": 0, "totalBytes": 0, "percent": 0}, "filesystems": []},
            "services": [],
            "containers": [],
            "snapshotError": str(exc),
        }
    body = {
        "schemaVersion": "v1",
        "messageType": "heartbeat",
        "messageId": f"msg-{int(time.time() * 1000)}",
        "sentAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "agentId": AGENT_ID,
        "nodeId": NODE_ID,
        "payload": payload,
    }
    if action_results:
        body["actionResults"] = action_results
    req = urllib.request.Request(
        CORE_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        raw = response.read().decode("utf-8")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}


def bootstrap():
    global CORE_BASE_URL, CORE_URL, INTERVAL_SECONDS, NODE_ID, AGENT_ID, SERVICES, STORAGE_DRIVES

    load_env_file(DEFAULT_ENV_PATH)
    CORE_BASE_URL = os.environ.get("HCC_CORE_BASE_URL", CORE_BASE_URL).strip().rstrip("/")
    CORE_URL = os.environ.get("HCC_CORE_HEARTBEAT_URL", CORE_URL).strip()
    if not CORE_URL and CORE_BASE_URL:
        CORE_URL = f"{CORE_BASE_URL}/api/v1/agent/heartbeat"
    INTERVAL_SECONDS = float(os.environ.get("HCC_AGENT_INTERVAL_SECONDS", str(INTERVAL_SECONDS)))
    NODE_ID = os.environ.get("HCC_AGENT_NODE_ID", NODE_ID)
    AGENT_ID = os.environ.get("HCC_AGENT_ID", AGENT_ID)
    SERVICES = [s.strip() for s in os.environ.get("HCC_SERVICES", ",".join(SERVICES)).split(",") if s.strip()]
    STORAGE_DRIVES = [
        d.strip().upper() for d in os.environ.get("HCC_STORAGE_DRIVES", ",".join(STORAGE_DRIVES)).split(",") if d.strip()
    ]


def main():
    bootstrap()
    if not CORE_URL:
        raise SystemExit("Missing HCC_CORE_HEARTBEAT_URL or HCC_CORE_BASE_URL environment variable.")
    agent_log(f"hcc-agent sending heartbeat to {CORE_URL}")
    print(f"hcc-agent sending heartbeat to {CORE_URL}")
    while True:
        try:
            response = send_heartbeat()
            pending = response.get("pendingActions") or []
            if pending:
                results = process_pending_actions(pending)
                send_heartbeat(action_results=results)
                agent_log(f"processed {len(results)} action(s)")
                print(f"processed {len(results)} action(s)")
            else:
                agent_log("heartbeat sent")
                print("heartbeat sent")
        except Exception as exc:
            agent_log(f"heartbeat failed: {exc}")
            print(f"heartbeat failed: {exc}")
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
