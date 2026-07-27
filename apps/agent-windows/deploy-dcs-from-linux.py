#!/usr/bin/env python3
import csv
import os
import sys

try:
    import winrm
except ImportError:
    print("Install pywinrm first: pip3 install pywinrm", file=sys.stderr)
    sys.exit(1)


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
INVENTORY = os.path.join(SCRIPT_DIR, "agents.inventory.dc.csv")
BOOTSTRAP_URL = os.environ.get(
    "HCC_BOOTSTRAP_URL",
    "http://192.168.4.237:3000/downloads/bootstrap-server-core.ps1",
)
RUN_AS_ACCOUNT = os.environ.get(
    "HCC_RUN_AS_ACCOUNT",
    r"WEB-FLIP\svc-hcc-agent$",
)


def load_rows(path):
    rows = []
    with open(path, newline="", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(",")
            if len(parts) < 7:
                raise ValueError(f"Invalid inventory row: {line}")
            rows.append(
                {
                    "host": parts[0].strip(),
                    "node_id": parts[1].strip(),
                    "agent_id": parts[2].strip(),
                    "core_base_url": parts[3].strip(),
                    "interval": parts[4].strip(),
                    "services": parts[5].strip().strip('"'),
                    "storage_drives": parts[6].strip(),
                }
            )
    return rows


def ps(session, script):
    result = session.run_ps(script)
    stdout = (result.std_out or b"").decode("utf-8", errors="replace").strip()
    stderr = (result.std_err or b"").decode("utf-8", errors="replace").strip()
    if result.status_code != 0:
        raise RuntimeError(stderr or stdout or f"PowerShell exit {result.status_code}")
    return stdout


def deploy_host(row, username, password):
    print(f"---- {row['host']} ({row['node_id']}) ----")
    session = winrm.Session(
        row["host"],
        auth=(username, password),
        transport="ntlm",
        server_cert_validation="ignore",
    )
    bootstrap_path = r"C:\Windows\Temp\hcc-bootstrap.ps1"
    script = f"""
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri '{BOOTSTRAP_URL}' -OutFile '{bootstrap_path}' -UseBasicParsing
    & '{bootstrap_path}' `
      -NodeId '{row['node_id']}' `
      -AgentId '{row['agent_id']}' `
      -CoreBaseUrl '{row['core_base_url']}' `
      -Interval '{row['interval']}' `
      -Services '{row['services']}' `
      -StorageDrives '{row['storage_drives']}' `
      -RunAsAccount '{RUN_AS_ACCOUNT}'
    Get-Service -Name 'HCC-Agent' -ErrorAction SilentlyContinue | Format-List Name, Status, StartType
    $agent = Join-Path $env:ProgramFiles 'HCC-Agent\\heartbeat_sender.ps1'
    if (Test-Path $agent) {{
      powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $agent -Once
    }}
    if (Test-Path 'C:\\ProgramData\\HCC-Agent\\agent.log') {{
      Get-Content 'C:\\ProgramData\\HCC-Agent\\agent.log' -Tail 8
    }}
    """
    output = ps(session, script)
    print(output)
    print(f"Deployed {row['node_id']} successfully.")


def main():
    username = os.environ.get("HCC_DC_USER", "").strip()
    password = os.environ.get("HCC_DC_PASSWORD", "").strip()
    if not username or not password:
        print(
            "Set domain credentials first:\n"
            "  export HCC_DC_USER='WEB-FLIP\\\\Administrator'\n"
            "  export HCC_DC_PASSWORD='your-password'\n"
            "  python3 deploy-dcs-from-linux.py",
            file=sys.stderr,
        )
        sys.exit(1)

    inventory = sys.argv[1] if len(sys.argv) > 1 else INVENTORY
    rows = load_rows(inventory)
    for row in rows:
        deploy_host(row, username, password)


if __name__ == "__main__":
    main()
