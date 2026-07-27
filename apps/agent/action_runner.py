import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import time
import urllib.request


ALLOWED_SERVICES = {
    "docker",
    "ssh",
    "ufw",
    "nginx",
    "postgresql",
    "mysql",
    "mariadb",
}


def configured_services():
    raw = os.environ.get("HCC_SERVICES", "").strip()
    if raw:
        return {item.strip().lower() for item in raw.split(",") if item.strip()}
    return ALLOWED_SERVICES

CONTAINER_ALLOWLIST = [
    item.strip()
    for item in os.environ.get(
        "HCC_CONTAINERS",
        "nextcloud,jellyfin,mariadb,postgres,redis,nginx,traefik,caddy",
    ).split(",")
    if item.strip()
]

INSTALL_DIR = os.environ.get("HCC_AGENT_INSTALL_DIR", "/opt/hcc-agent")
STATE_DIR = os.environ.get("HCC_AGENT_STATE_DIR", "/var/lib/hcc-agent")
ENV_PATH = os.environ.get("HCC_AGENT_ENV_PATH", "/etc/hcc-agent.env")
AGENT_VERSION = os.environ.get("HCC_AGENT_VERSION", "1.0.0").strip() or "1.0.0"
UPDATE_MANIFEST = os.path.join(STATE_DIR, "update-manifest.json")
UPDATE_HELPER_UNIT = "hcc-agent-update.service"


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


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _set_env_value(path, key, value):
    lines = []
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    updated = False
    prefix = f"{key}="
    result = []
    for line in lines:
        if line.startswith(prefix):
            result.append(f"{key}={value}")
            updated = True
        else:
            result.append(line)
    if not updated:
        result.append(f"{key}={value}")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(result) + "\n")


def _write_update_manifest(source_dir, version):
    os.makedirs(STATE_DIR, exist_ok=True)
    manifest = {
        "version": version,
        "sourceDir": source_dir,
        "installDir": INSTALL_DIR,
        "envPath": ENV_PATH,
        "stateDir": STATE_DIR,
        "queuedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    with open(UPDATE_MANIFEST, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh)


def _trigger_update_helper(source_dir):
    installed_helper = os.path.join(INSTALL_DIR, "apply-update.sh")
    helper = installed_helper if os.path.isfile(installed_helper) else os.path.join(source_dir, "apply-update.sh")
    if not os.path.isfile(helper):
        return False, "update helper not found in install dir or staged package"

    code, _ = run(["systemctl", "start", UPDATE_HELPER_UNIT], timeout=15.0)
    if code == 0:
        return True, "systemd helper started"

    subprocess.Popen(
        ["/bin/bash", helper],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    return True, "detached helper started"


def agent_self_update(params):
    params = params or {}
    target_version = str(params.get("version") or "").strip()
    package_url = str(params.get("packageUrl") or "").strip()
    expected_sha = str(params.get("sha256") or "").strip().lower()
    if not target_version or not package_url:
        return 400, "agent.self_update requires version and packageUrl"
    if target_version == AGENT_VERSION:
        return 0, f"already on version {target_version}"

    staging_dir = os.path.join(STATE_DIR, "staging")
    os.makedirs(staging_dir, exist_ok=True)
    archive_path = os.path.join(staging_dir, "hcc-agent-linux.tar.gz")

    try:
        urllib.request.urlretrieve(package_url, archive_path)
        if expected_sha:
            actual_sha = _sha256_file(archive_path)
            if actual_sha != expected_sha:
                return 409, f"package sha256 mismatch expected={expected_sha} actual={actual_sha}"

        extract_root = os.path.join(staging_dir, "extract")
        if os.path.isdir(extract_root):
            shutil.rmtree(extract_root)
        os.makedirs(extract_root, exist_ok=True)
        with tarfile.open(archive_path, "r:gz") as archive:
            archive.extractall(extract_root)

        source_dir = os.path.join(extract_root, "hcc-agent")
        if not os.path.isdir(source_dir):
            return 500, "package missing hcc-agent directory"

        _write_update_manifest(source_dir, target_version)
        ok, mode = _trigger_update_helper(source_dir)
        if not ok:
            return 500, mode
    except Exception as exc:
        return 500, f"self-update staging failed: {exc}"

    return (
        0,
        f"update scheduled for version {target_version} ({mode}; helper will stop/install/start)",
    )


def _vm_command(vm_type, vmid, verb):
    if vm_type == "lxc":
        mapping = {
            "start": ["pct", "start", vmid],
            "stop": ["pct", "stop", vmid],
            "shutdown": ["pct", "shutdown", vmid],
            "reboot": ["pct", "reboot", vmid],
        }
    else:
        mapping = {
            "start": ["qm", "start", vmid],
            "stop": ["qm", "stop", vmid],
            "shutdown": ["qm", "shutdown", vmid],
            "reboot": ["qm", "reboot", vmid],
        }
    return mapping.get(verb)


def _container_allowed(name):
    container = str(name or "").strip()
    if not container:
        return False
    code, out = run(["docker", "ps", "-a", "--format", "{{.Names}}"], timeout=3.0)
    if code != 0:
        return False
    names = {line.strip() for line in out.splitlines() if line.strip()}
    if container not in names:
        return False
    if not CONTAINER_ALLOWLIST:
        return True
    lowered = container.lower()
    return any(token.lower() in lowered for token in CONTAINER_ALLOWLIST)


def execute_action(action_id, target=None, params=None):
    params = params or {}
    vm_type = params.get("vmType", "qemu")

    if action_id == "agent.self_update":
        return agent_self_update(params)

    if action_id == "host.reboot":
        code, out = run(["systemctl", "reboot"], timeout=5.0)
        return code, out or "reboot requested"

    if action_id == "host.shutdown":
        code, out = run(["systemctl", "poweroff"], timeout=5.0)
        return code, out or "shutdown requested"

    if action_id.startswith("vm."):
        if not target:
            return 400, "vm target required"
        verb = action_id.split(".", 1)[1]
        command = _vm_command(vm_type, str(target), verb)
        if not command:
            return 400, f"unsupported vm action: {action_id}"
        code, out = run(command, timeout=30.0)
        return code, out or f"{action_id} {target}"

    if action_id.startswith("service."):
        if not target:
            return 400, "service target required"
        service = str(target).strip()
        if service.lower() not in configured_services():
            return 403, f"service not allowlisted: {service}"
        verb = action_id.split(".", 1)[1]
        if verb not in {"start", "stop", "restart"}:
            return 400, f"unsupported service action: {action_id}"
        code, out = run(["systemctl", verb, service], timeout=20.0)
        return code, out or f"{action_id} {service}"

    if action_id.startswith("container."):
        if not target:
            return 400, "container target required"
        container = str(target).strip()
        if not _container_allowed(container):
            return 403, f"container not allowlisted or missing: {container}"
        verb = action_id.split(".", 1)[1]
        if verb not in {"start", "stop", "restart"}:
            return 400, f"unsupported container action: {action_id}"
        code, out = run(["docker", verb, container], timeout=60.0)
        return code, out or f"{action_id} {container}"

    return 404, f"unsupported action: {action_id}"
