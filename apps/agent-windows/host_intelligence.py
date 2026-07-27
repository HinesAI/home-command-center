import json
import os
import platform
import subprocess


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


def hardware_profile():
    data = ps_json(
        """
        $cs = Get-CimInstance Win32_ComputerSystem
        $bios = Get-CimInstance Win32_BIOS
        $model = [string]$cs.Model
        $manufacturer = [string]$cs.Manufacturer
        $hypervisor = [bool]$cs.HypervisorPresent
        $vmHints = @('Virtual Machine','VMware','KVM','VirtualBox','QEMU','Hyper-V','Microsoft Virtual')
        $isVM = $hypervisor -or ($vmHints | Where-Object { $model -like "*$_*" -or $manufacturer -like "*$_*" })
        [pscustomobject]@{
            virtualizationType = if ($hypervisor) { 'hyperv' } elseif ($isVM) { 'vm' } else { 'none' }
            isVirtualMachine = [bool]$isVM
            isContainer = $false
            isPhysical = -not [bool]$isVM
        }
        """
    )
    if not isinstance(data, dict):
        return {
            "virtualizationType": "unknown",
            "isVirtualMachine": False,
            "isContainer": False,
            "isPhysical": True,
        }
    return {
        "virtualizationType": data.get("virtualizationType") or "unknown",
        "isVirtualMachine": bool(data.get("isVirtualMachine")),
        "isContainer": bool(data.get("isContainer")),
        "isPhysical": bool(data.get("isPhysical")),
    }


def detect_host_role(hardware):
    data = ps_json(
        """
        $os = Get-CimInstance Win32_OperatingSystem
        [pscustomobject]@{
            productType = [int]$os.ProductType
            caption = [string]$os.Caption
        }
        """
    )
    product_type = int((data or {}).get("productType") or 0)
    caption = str((data or {}).get("caption") or "").lower()

    if product_type == 1 or "windows 10" in caption or "windows 11" in caption:
        return "windows-client"
    if product_type in {2, 3} or "server" in caption or "domain controller" in caption:
        return "windows-server"
    if hardware.get("isVirtualMachine"):
        return "windows-server"
    return "windows-client"


def cpu_info():
    data = ps_json(
        """
        $cpus = Get-CimInstance Win32_Processor
        $model = ($cpus | Select-Object -First 1 -ExpandProperty Name)
        $logical = ($cpus | Measure-Object -Property NumberOfLogicalProcessors -Sum).Sum
        $cores = ($cpus | Measure-Object -Property NumberOfCores -Sum).Sum
        $sockets = ($cpus | Select-Object -ExpandProperty SocketDesignation | Sort-Object -Unique | Measure-Object).Count
        [pscustomobject]@{
            model = [string]$model
            logicalCpus = [int]$logical
            physicalCores = [int]$cores
            sockets = [int]$sockets
        }
        """
    )
    if not isinstance(data, dict):
        return {
            "model": platform.processor() or "Unknown CPU",
            "logicalCpus": os.cpu_count() or 0,
            "physicalCores": os.cpu_count() or 0,
            "sockets": 1,
            "cores": os.cpu_count() or 0,
            "threads": os.cpu_count() or 0,
            "arch": platform.machine(),
        }

    logical = int(data.get("logicalCpus") or 0)
    physical = int(data.get("physicalCores") or logical)
    return {
        "model": data.get("model") or "Unknown CPU",
        "logicalCpus": logical,
        "physicalCores": physical,
        "sockets": int(data.get("sockets") or 1),
        "cores": logical,
        "threads": logical,
        "arch": platform.machine(),
    }


def section_catalog(host_role):
    if host_role == "windows-client":
        return {"services": True, "containers": False, "vms": False, "storage": True}
    if host_role == "windows-server":
        return {"services": True, "containers": False, "vms": False, "storage": True}
    return {"services": True, "containers": False, "vms": False, "storage": True}


def action_catalog(host_role):
    common_host = [
        {"id": "host.reboot", "label": "Reboot Host", "scope": "host", "dangerous": True},
        {"id": "host.shutdown", "label": "Shutdown Host", "scope": "host", "dangerous": True},
    ]
    if host_role == "windows-server":
        return [
            {"id": "service.restart", "label": "Restart Service", "scope": "service", "targetRequired": True},
            {"id": "service.stop", "label": "Stop Service", "scope": "service", "targetRequired": True, "dangerous": True},
            {"id": "service.start", "label": "Start Service", "scope": "service", "targetRequired": True},
        ] + common_host
    return common_host


def host_extensions(host_role, hardware):
    cpu = cpu_info()
    extensions = {
        "hostRole": host_role,
        "deviceCategory": "client" if host_role == "windows-client" else "server",
        "cpu": cpu,
        "capabilities": {
            "hostRole": host_role,
            "deviceCategory": "client" if host_role == "windows-client" else "server",
            "actions": action_catalog(host_role),
            "sections": section_catalog(host_role),
        },
    }
    if hardware.get("isPhysical"):
        extensions["cpu"]["physical"] = True
    extensions["workloads"] = {
        "kind": host_role,
        "focus": ["services", "storage"] if host_role == "windows-server" else ["storage"],
    }
    return extensions
