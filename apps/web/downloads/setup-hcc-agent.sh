#!/usr/bin/env bash
set -euo pipefail

CORE_BASE_URL="${HCC_CORE_BASE_URL:-http://hcc.example.local}"
WEB_BASE_URL="${HCC_WEB_BASE_URL:-http://hcc.example.local}"
NODE_ID="${HCC_AGENT_NODE_ID:-$(hostname -s | tr '[:upper:]' '[:lower:]')}"
AGENT_ID="${HCC_AGENT_ID:-agent-${NODE_ID}}"
INTERVAL="${HCC_AGENT_INTERVAL_SECONDS:-120}"
SERVICES="${HCC_SERVICES:-docker,ssh,ufw}"
STORAGE_PATHS="${HCC_STORAGE_PATHS:-/,/srv,/mnt/storage,/media/storage}"
FORCE="${HCC_AGENT_FORCE:-0}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALLER="${SCRIPT_DIR}/install-linux-agent.sh"

if [[ ! -f "$INSTALLER" ]]; then
  WORK_DIR="$(mktemp -d)"
  trap 'rm -rf "$WORK_DIR"' EXIT
  curl -fsSL "${WEB_BASE_URL}/downloads/hcc-agent-linux.tar.gz" -o "${WORK_DIR}/hcc-agent-linux.tar.gz"
  tar -xzf "${WORK_DIR}/hcc-agent-linux.tar.gz" -C "$WORK_DIR"
  INSTALLER="${WORK_DIR}/hcc-agent/install-linux-agent.sh"
fi

if systemctl is-active --quiet hcc-agent.service && [[ "$FORCE" != "1" ]]; then
  echo "hcc-agent already running; set HCC_AGENT_FORCE=1 to reinstall"
  exit 0
fi

exec "$INSTALLER" \
  --core-base-url "$CORE_BASE_URL" \
  --node-id "$NODE_ID" \
  --agent-id "$AGENT_ID" \
  --interval "$INTERVAL" \
  --services "$SERVICES" \
  --storage-paths "$STORAGE_PATHS"
