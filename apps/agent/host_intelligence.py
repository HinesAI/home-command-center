import json
import os
import platform
import re


def run(command, timeout=2.0):
    import subprocess

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


def is_proxmox():
    if os.path.exists("/etc/pve/.version"):
        return True
    code, out = run(["pveversion"])
    return code == 0 and bool(out)


def detect_host_role(hardware):
    if is_proxmox():
        return "proxmox"
    os_release = read_os_release()
    distro_id = (os_release.get("ID") or "").lower()
    id_like = (os_release.get("ID_LIKE") or "").lower()
    if distro_id == "ubuntu" or "ubuntu" in id_like:
        return "ubuntu-server"
    if hardware.get("isVirtualMachine"):
        return "vm-linux"
    if hardware.get("isPhysical"):
        return "physical-linux"
    return "generic-linux"


def cpu_info():
    model = "Unknown CPU"
    logical_cpus = 0
    physical_cores = 0
    sockets = 0
    cores_per_socket = 0
    threads_per_core = 0

    try:
        with open("/proc/cpuinfo", "r", encoding="utf-8") as fh:
            for line in fh:
                if line.lower().startswith("model name") and model == "Unknown CPU":
                    model = line.split(":", 1)[1].strip()
                if line.lower().startswith("processor"):
                    logical_cpus += 1
    except FileNotFoundError:
        pass

    code, out = run(["nproc"])
    if code == 0 and out.isdigit():
        logical_cpus = max(logical_cpus, int(out))

    code, out = run(["lscpu", "-J"], timeout=2.5)
    if code == 0 and out:
        try:
            payload = json.loads(out)
            fields = {}
            for field in payload.get("lscpu") or []:
                key = field.get("field", "").strip().strip(":")
                fields[key] = field.get("data", "")

            if fields.get("Model name"):
                model = fields["Model name"]

            def _int_field(name):
                raw = fields.get(name, "")
                token = str(raw).split()[0]
                return int(token) if token.isdigit() else 0

            logical_cpus = _int_field("CPU(s)") or logical_cpus
            sockets = _int_field("Socket(s)")
            cores_per_socket = _int_field("Core(s) per socket")
            threads_per_core = _int_field("Thread(s) per core")
            if cores_per_socket and sockets:
                physical_cores = cores_per_socket * sockets
            elif logical_cpus and threads_per_core:
                physical_cores = max(1, logical_cpus // max(1, threads_per_core))
        except (json.JSONDecodeError, ValueError):
            pass

    if not logical_cpus:
        logical_cpus = physical_cores or 1
    if not physical_cores:
        physical_cores = logical_cpus

    return {
        "model": model,
        "logicalCpus": logical_cpus,
        "physicalCores": physical_cores,
        "sockets": sockets,
        "coresPerSocket": cores_per_socket,
        "threadsPerCore": threads_per_core,
        "cores": logical_cpus,
        "threads": logical_cpus,
        "arch": platform.machine(),
    }


def _normalize_vm_status(raw):
    value = (raw or "").lower()
    if value in {"running", "started", "active"}:
        return "running"
    if value in {"stopped", "stopped (disabled)"}:
        return "stopped"
    if "paused" in value:
        return "paused"
    return value or "unknown"


PROXMOX_OSTYPE_LABELS = {
    "l24": "Linux 2.4",
    "l26": "Linux",
    "l27": "Linux",
    "other": "Other",
    "solaris": "Solaris",
    "wxp": "Windows XP",
    "w2k": "Windows 2000",
    "w2k3": "Windows Server 2003",
    "w2k8": "Windows Server 2008",
    "wvista": "Windows Vista",
    "win7": "Windows 7",
    "win8": "Windows 8",
    "win10": "Windows 10",
    "win11": "Windows 11",
    "ubuntu": "Ubuntu",
    "debian": "Debian",
    "centos": "CentOS",
    "archlinux": "Arch Linux",
    "fedora": "Fedora",
    "opensuse": "openSUSE",
    "alpine": "Alpine Linux",
    "gentoo": "Gentoo",
    "nspawn": "systemd-nspawn",
    "unmanaged": "Unmanaged",
}


def _read_proxmox_conf_value(vmid, kind, key):
    folder = "qemu-server" if kind == "qemu" else "lxc"
    path = f"/etc/pve/{folder}/{vmid}.conf"
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith(f"{key}:"):
                    return line.split(":", 1)[1].strip()
    except (FileNotFoundError, OSError):
        return None
    return None


def _vm_os_type(vmid, kind):
    raw = _read_proxmox_conf_value(vmid, kind, "ostype")
    if not raw:
        return "-"
    return PROXMOX_OSTYPE_LABELS.get(raw.lower(), raw)


def _parse_qm_list():
    code, out = run(["qm", "list"], timeout=4.0)
    if code != 0 or not out:
        return []
    rows = []
    for line in out.splitlines()[1:]:
        parts = re.split(r"\s+", line.strip())
        if len(parts) < 3:
            continue
        vmid, name, status = parts[0], parts[1], parts[2]
        mem_mb = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
        disk_gb = float(parts[4]) if len(parts) > 4 else 0.0
        pid = int(parts[5]) if len(parts) > 5 and str(parts[5]).isdigit() else None
        rows.append(
            {
                "id": vmid,
                "name": name,
                "type": "qemu",
                "status": _normalize_vm_status(status),
                "memoryMb": mem_mb,
                "diskGb": disk_gb,
                "pid": pid,
                "osType": _vm_os_type(vmid, "qemu"),
            }
        )
    return rows


def _parse_pct_list():
    code, out = run(["pct", "list"], timeout=4.0)
    if code != 0 or not out:
        return []
    rows = []
    for line in out.splitlines()[1:]:
        parts = re.split(r"\s+", line.strip())
        if len(parts) < 4:
            continue
        vmid, status, name = parts[0], parts[1], parts[2]
        rows.append(
            {
                "id": vmid,
                "name": name,
                "type": "lxc",
                "status": _normalize_vm_status(status),
                "memoryMb": 0,
                "diskGb": 0.0,
                "osType": _vm_os_type(vmid, "lxc"),
            }
        )
    return rows


def proxmox_vms():
    vms = _parse_qm_list() + _parse_pct_list()
    vms.sort(key=lambda item: int(item["id"]) if str(item["id"]).isdigit() else 99999)
    return vms


def docker_available():
    code, _ = run(["docker", "info"], timeout=3.0)
    return code == 0


def section_catalog(host_role, docker_ready=False):
    if host_role == "proxmox":
        return {"services": False, "containers": docker_ready, "vms": True, "storage": True}
    return {"services": True, "containers": docker_ready, "vms": False, "storage": True}


def container_action_defs():
    return [
        {"id": "container.start", "label": "Start", "scope": "container", "targetRequired": True},
        {"id": "container.stop", "label": "Stop", "scope": "container", "targetRequired": True, "dangerous": True},
        {"id": "container.restart", "label": "Restart", "scope": "container", "targetRequired": True},
    ]


def action_catalog(host_role, docker_ready=False):
    common_host = [
        {"id": "host.reboot", "label": "Reboot Host", "scope": "host", "dangerous": True},
        {"id": "host.shutdown", "label": "Shutdown Host", "scope": "host", "dangerous": True},
    ]
    maintainer = [
        {"id": "agent.self_update", "label": "Self Update Agent", "scope": "agent", "dangerous": True},
    ]
    container_actions = container_action_defs() if docker_ready else []
    if host_role == "proxmox":
        return [
            {"id": "vm.start", "label": "Start VM", "scope": "vm", "targetRequired": True},
            {"id": "vm.stop", "label": "Stop VM", "scope": "vm", "targetRequired": True, "dangerous": True},
            {"id": "vm.shutdown", "label": "Shutdown VM", "scope": "vm", "targetRequired": True},
            {"id": "vm.reboot", "label": "Reboot VM", "scope": "vm", "targetRequired": True},
        ] + container_actions + maintainer + common_host
    if host_role in {"ubuntu-server", "physical-linux", "generic-linux", "vm-linux"}:
        return [
            {"id": "service.restart", "label": "Restart Service", "scope": "service", "targetRequired": True},
            {"id": "service.stop", "label": "Stop Service", "scope": "service", "targetRequired": True, "dangerous": True},
            {"id": "service.start", "label": "Start Service", "scope": "service", "targetRequired": True},
        ] + container_actions + maintainer + common_host
    return maintainer + common_host


def host_extensions(host_role, hardware, docker_ready=False):
    cpu = cpu_info()
    extensions = {
        "hostRole": host_role,
        "deviceCategory": "server",
        "cpu": cpu,
        "capabilities": {
            "hostRole": host_role,
            "deviceCategory": "server",
            "actions": action_catalog(host_role, docker_ready),
            "sections": section_catalog(host_role, docker_ready),
        },
    }
    if host_role == "proxmox":
        focus = ["vms", "storage"]
        if docker_ready:
            focus.append("containers")
        extensions["workloads"] = {
            "kind": "proxmox",
            "vms": proxmox_vms(),
            "focus": focus,
        }
    else:
        focus = ["services", "storage"]
        if docker_ready:
            focus.insert(1, "containers")
        extensions["workloads"] = {
            "kind": host_role,
            "focus": focus,
        }
    if hardware.get("isPhysical"):
        extensions["cpu"]["physical"] = True
    return extensions
