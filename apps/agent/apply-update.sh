#!/usr/bin/env bash
# HCCv2 Linux update helper — runs outside hcc-agent.service (via systemd oneshot or detached).
# Reads /var/lib/hcc-agent/update-manifest.json, stops the agent, installs staged files, restarts.
set -euo pipefail

STATE_DIR="${HCC_AGENT_STATE_DIR:-/var/lib/hcc-agent}"
MANIFEST="${STATE_DIR}/update-manifest.json"
RESULT="${STATE_DIR}/update-result.json"
LOG="${STATE_DIR}/update.log"
INSTALL_DIR="${HCC_AGENT_INSTALL_DIR:-/opt/hcc-agent}"
ENV_PATH="${HCC_AGENT_ENV_PATH:-/etc/hcc-agent.env}"
AGENT_SERVICE="hcc-agent.service"

AGENT_FILES=(
  heartbeat_sender.py
  host_intelligence.py
  action_runner.py
  apply-update.sh
  hcc-agent.service
  hcc-agent-update.service
)

log() {
  local stamp
  stamp="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  echo "$stamp $*" | tee -a "$LOG"
}

write_result() {
  local ok="$1"
  local message="$2"
  python3 - "$RESULT" "$ok" "$message" <<'PY'
import json, sys, time
path, ok, message = sys.argv[1], sys.argv[2] == "true", sys.argv[3]
with open(path, "w", encoding="utf-8") as fh:
    json.dump(
        {
            "ok": ok,
            "message": message,
            "completedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
        fh,
    )
PY
}

read_manifest() {
  python3 - "$MANIFEST" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    data = json.load(fh)
for key in ("version", "sourceDir", "installDir", "envPath", "stateDir"):
    print(data.get(key, ""))
PY
}

set_env_version() {
  local path="$1"
  local version="$2"
  python3 - "$path" "HCC_AGENT_VERSION" "$version" <<'PY'
import sys
path, key, value = sys.argv[1], sys.argv[2], sys.argv[3]
lines = []
if __import__("os").path.exists(path):
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
prefix = f"{key}="
out, found = [], False
for line in lines:
    if line.startswith(prefix):
        out.append(f"{key}={value}")
        found = True
    else:
        out.append(line)
if not found:
    out.append(f"{key}={value}")
with open(path, "w", encoding="utf-8") as fh:
    fh.write("\n".join(out) + "\n")
PY
}

on_error() {
  local code=$?
  log "update failed (exit $code)"
  write_result false "update failed with exit $code; see $LOG"
  systemctl start "$AGENT_SERVICE" 2>/dev/null || true
  exit "$code"
}

trap on_error ERR

if [[ ! -f "$MANIFEST" ]]; then
  echo "missing manifest: $MANIFEST" >&2
  exit 1
fi

mapfile -t manifest_fields < <(read_manifest)
VERSION="${manifest_fields[0]}"
SOURCE_DIR="${manifest_fields[1]}"
INSTALL_DIR="${manifest_fields[2]:-$INSTALL_DIR}"
ENV_PATH="${manifest_fields[3]:-$ENV_PATH}"
STATE_DIR="${manifest_fields[4]:-$STATE_DIR}"

if [[ -z "$VERSION" || -z "$SOURCE_DIR" || ! -d "$SOURCE_DIR" ]]; then
  echo "invalid manifest: version=$VERSION sourceDir=$SOURCE_DIR" >&2
  exit 1
fi

log "applying version $VERSION from $SOURCE_DIR"

log "stopping $AGENT_SERVICE"
systemctl stop "$AGENT_SERVICE" || true
sleep 2

install -d -m 755 "$INSTALL_DIR"
for file in "${AGENT_FILES[@]}"; do
  src="${SOURCE_DIR}/${file}"
  if [[ -f "$src" ]]; then
    if [[ "$file" == *.sh ]]; then
      install -m 755 "$src" "${INSTALL_DIR}/${file}"
    elif [[ "$file" == *.service ]]; then
      install -m 644 "$src" "${INSTALL_DIR}/${file}"
      if [[ "$file" == "hcc-agent-update.service" ]]; then
        install -m 644 "$src" "/etc/systemd/system/${file}"
      elif [[ "$file" == "hcc-agent.service" ]]; then
        install -m 644 "$src" "/etc/systemd/system/${file}"
      fi
    elif [[ "$file" == *.py && "$file" != "action_runner.py" ]]; then
      install -m 755 "$src" "${INSTALL_DIR}/${file}"
    else
      install -m 644 "$src" "${INSTALL_DIR}/${file}"
    fi
    log "installed ${file}"
  fi
done

set_env_version "$ENV_PATH" "$VERSION"
log "set HCC_AGENT_VERSION=$VERSION"

systemctl daemon-reload
log "starting $AGENT_SERVICE"
systemctl start "$AGENT_SERVICE"

write_result true "updated to version $VERSION"
log "update complete -> $VERSION"
