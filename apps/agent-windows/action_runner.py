import subprocess


ALLOWED_SERVICES = {
    "w3svc",
    "dns",
    "dhcp",
    "ntds",
    "kdc",
    "spooler",
    "winrm",
    "lanmanserver",
    "lanmanworkstation",
    "eventlog",
    "docker",
}


def run(command, timeout=20.0):
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )
        output = (result.stdout or "").strip()
        err = (result.stderr or "").strip()
        if err and output:
            output = f"{output}\n{err}"
        elif err:
            output = err
        return result.returncode, output
    except subprocess.TimeoutExpired:
        return 124, "command timed out"
    except FileNotFoundError:
        return 127, "command not found"


def execute_action(action_id, target=None, params=None):
    params = params or {}

    if action_id == "host.reboot":
        code, out = run(["shutdown", "/r", "/t", "0", "/f"], timeout=5.0)
        return code, out or "reboot requested"

    if action_id == "host.shutdown":
        code, out = run(["shutdown", "/s", "/t", "0", "/f"], timeout=5.0)
        return code, out or "shutdown requested"

    if action_id.startswith("service."):
        if not target:
            return 400, "service target required"
        service = str(target).strip()
        if service.lower() not in ALLOWED_SERVICES:
            return 403, f"service not allowlisted: {service}"
        verb = action_id.split(".", 1)[1]
        if verb not in {"start", "stop", "restart"}:
            return 400, f"unsupported service action: {action_id}"
        ps_verb = {"start": "Start-Service", "stop": "Stop-Service", "restart": "Restart-Service"}[verb]
        script = f"$ErrorActionPreference='Stop'; {ps_verb} -Name '{service}' -Force"
        code, out = run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
            timeout=30.0,
        )
        return code, out or f"{action_id} {service}"

    return 404, f"unsupported action: {action_id}"
