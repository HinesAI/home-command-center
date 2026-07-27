#!/usr/bin/env python3
"""Repair HCC agent scheduling on domain controllers via WinRM."""
import os
import sys

try:
    import winrm
except ImportError:
    print("Install pywinrm first: pip3 install pywinrm", file=sys.stderr)
    sys.exit(1)

HOSTS = [
    ("192.168.4.100", "hinesdc1"),
    ("192.168.4.191", "hinesdc2"),
    ("192.168.4.147", "hinesdc3"),
]
FIX_URL = os.environ.get(
    "HCC_FIX_TASK_URL",
    "http://192.168.4.237:3000/downloads/ad/fix-hcc-agent-task.ps1",
)
HEARTBEAT_URL = os.environ.get(
    "HCC_HEARTBEAT_URL",
    "http://192.168.4.237:3000/downloads/heartbeat_sender.ps1",
)
REGISTER_URL = os.environ.get(
    "HCC_REGISTER_TASK_URL",
    "http://192.168.4.237:3000/downloads/ad/register-hcc-agent-task.ps1",
)
WATCHDOG_URL = os.environ.get(
    "HCC_WATCHDOG_URL",
    "http://192.168.4.237:3000/downloads/ad/watchdog-hcc-agent.ps1",
)


def ps(session, script):
    result = session.run_ps(script)
    stdout = (result.std_out or b"").decode("utf-8", errors="replace").strip()
    stderr = (result.std_err or b"").decode("utf-8", errors="replace").strip()
    if result.status_code != 0:
        raise RuntimeError(stderr or stdout or f"PowerShell exit {result.status_code}")
    return stdout


def repair_host(host, node_id, username, password):
    print(f"---- {host} ({node_id}) ----")
    session = winrm.Session(
        host,
        auth=(username, password),
        transport="ntlm",
        server_cert_validation="ignore",
    )
    script = f"""
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $dir = Join-Path $env:ProgramFiles 'HCC-Agent'
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    Invoke-WebRequest -Uri '{REGISTER_URL}' -OutFile (Join-Path $dir 'register-hcc-agent-task.ps1') -UseBasicParsing
    Invoke-WebRequest -Uri '{WATCHDOG_URL}' -OutFile (Join-Path $dir 'watchdog-hcc-agent.ps1') -UseBasicParsing
    Invoke-WebRequest -Uri '{FIX_URL}' -OutFile (Join-Path $dir 'fix-hcc-agent-task.ps1') -UseBasicParsing
    Invoke-WebRequest -Uri '{HEARTBEAT_URL}' -OutFile (Join-Path $dir 'heartbeat_sender.ps1') -UseBasicParsing
    & (Join-Path $dir 'fix-hcc-agent-task.ps1')
    """
    output = ps(session, script)
    print(output)
    print(f"Repaired {node_id}.")


def main():
    username = os.environ.get("HCC_DC_USER", "").strip()
    password = os.environ.get("HCC_DC_PASSWORD", "").strip()
    if not username or not password:
        print(
            "Set domain credentials first:\n"
            "  export HCC_DC_USER='WEB-FLIP\\\\Administrator'\n"
            "  export HCC_DC_PASSWORD='your-password'\n"
            "  python3 repair-dcs-from-linux.py",
            file=sys.stderr,
        )
        sys.exit(1)

    for host, node_id in HOSTS:
        repair_host(host, node_id, username, password)


if __name__ == "__main__":
    main()
