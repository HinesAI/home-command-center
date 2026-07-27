#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="/opt/hcc-agent"
ENV_PATH="/etc/hcc-agent.env"
SERVICE_PATH="/etc/systemd/system/hcc-agent.service"

CORE_BASE_URL=""
CORE_HEARTBEAT_URL=""
NODE_ID=""
AGENT_ID=""
INTERVAL="120"
SERVICES="docker,ssh,ufw"
STORAGE_PATHS="/,/srv,/mnt/storage,/media/storage"
CONTAINERS="nextcloud,jellyfin,mariadb,postgres,redis,nginx,traefik,caddy"

usage() {
  cat <<'EOF'
Usage:
  sudo ./install-linux-agent.sh --core-base-url URL --node-id ID --agent-id ID [options]
  sudo ./install-linux-agent.sh --core-heartbeat-url URL --node-id ID --agent-id ID [options]

Required:
  --node-id ID              Unique node id for this host
  --agent-id ID             Unique agent id for this host
  Either one of:
    --core-base-url URL     Example: http://192.168.4.237:18080
    --core-heartbeat-url URL

Optional:
  --interval SECONDS        Heartbeat interval (default: 120)
  --services CSV            systemd service names to probe
  --storage-paths CSV       Storage paths to report
  --containers CSV          Container name fragments to report
EOF
}

while (($# > 0)); do
  case "$1" in
    --core-base-url)
      CORE_BASE_URL="${2:-}"
      shift 2
      ;;
    --core-heartbeat-url)
      CORE_HEARTBEAT_URL="${2:-}"
      shift 2
      ;;
    --node-id)
      NODE_ID="${2:-}"
      shift 2
      ;;
    --agent-id)
      AGENT_ID="${2:-}"
      shift 2
      ;;
    --interval)
      INTERVAL="${2:-}"
      shift 2
      ;;
    --services)
      SERVICES="${2:-}"
      shift 2
      ;;
    --storage-paths)
      STORAGE_PATHS="${2:-}"
      shift 2
      ;;
    --containers)
      CONTAINERS="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$NODE_ID" || -z "$AGENT_ID" ]]; then
  echo "Missing required --node-id or --agent-id." >&2
  usage
  exit 1
fi

if [[ -z "$CORE_BASE_URL" && -z "$CORE_HEARTBEAT_URL" ]]; then
  echo "Provide --core-base-url or --core-heartbeat-url." >&2
  usage
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required but not installed." >&2
  exit 1
fi

install -d -m 755 "$INSTALL_DIR"
install -d -m 750 /var/lib/hcc-agent
install -m 755 "${SCRIPT_DIR}/heartbeat_sender.py" "${INSTALL_DIR}/heartbeat_sender.py"
install -m 644 "${SCRIPT_DIR}/host_intelligence.py" "${INSTALL_DIR}/host_intelligence.py"
install -m 644 "${SCRIPT_DIR}/action_runner.py" "${INSTALL_DIR}/action_runner.py"
install -m 755 "${SCRIPT_DIR}/apply-update.sh" "${INSTALL_DIR}/apply-update.sh"
install -m 644 "${SCRIPT_DIR}/hcc-agent.service" "$SERVICE_PATH"
install -m 644 "${SCRIPT_DIR}/hcc-agent-update.service" "/etc/systemd/system/hcc-agent-update.service"

cat > "$ENV_PATH" <<EOF
HCC_CORE_BASE_URL=${CORE_BASE_URL}
HCC_CORE_HEARTBEAT_URL=${CORE_HEARTBEAT_URL}
HCC_AGENT_NODE_ID=${NODE_ID}
HCC_AGENT_ID=${AGENT_ID}
HCC_AGENT_VERSION=1.0.5
HCC_AGENT_INTERVAL_SECONDS=${INTERVAL}
HCC_SERVICES=${SERVICES}
HCC_STORAGE_PATHS=${STORAGE_PATHS}
HCC_CONTAINERS=${CONTAINERS}
EOF

chmod 600 "$ENV_PATH"

systemctl daemon-reload
systemctl enable --now hcc-agent.service
systemctl restart hcc-agent.service

echo "Installed hcc-agent successfully."
echo "Check status: sudo systemctl status hcc-agent.service"
echo "Check logs:   sudo journalctl -u hcc-agent.service -f"

