#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INVENTORY_FILE="${1:-}"
DRY_RUN="${DRY_RUN:-false}"
SSH_OPTS="${SSH_OPTS:--o BatchMode=yes -o ConnectTimeout=10}"
SSH_IDENTITY_FILE="${SSH_IDENTITY_FILE:-}"
if [[ -z "$SSH_IDENTITY_FILE" && -f "${HOME}/.ssh/id_ed25519_hcc_rollout" ]]; then
  SSH_IDENTITY_FILE="${HOME}/.ssh/id_ed25519_hcc_rollout"
fi

usage() {
  cat <<'EOF'
Usage:
  ./rollout-linux-agents.sh /path/to/agents.inventory.csv

Inventory CSV columns:
  host,user,node_id,agent_id,core_base_url,interval,services,storage_paths,containers

Notes:
  - Lines starting with # are ignored
  - Blank lines are ignored
  - Set DRY_RUN=true to preview commands without executing
  - Override SSH options with SSH_OPTS env var if needed
  - Set SSH_IDENTITY_FILE=/path/to/key to force a specific SSH key
EOF
}

run_cmd() {
  if [[ "$DRY_RUN" == "true" ]]; then
    echo "[dry-run] $*"
    return 0
  fi
  "$@"
}

build_ssh_cmd() {
  local base="$1"
  local prefix="$base"
  if [[ "$base" == "ssh" ]]; then
    prefix="ssh -n"
  fi
  if [[ -n "$SSH_IDENTITY_FILE" ]]; then
    echo "$prefix -i ${SSH_IDENTITY_FILE}"
  else
    echo "$prefix"
  fi
}

if [[ "$INVENTORY_FILE" == "-h" || "$INVENTORY_FILE" == "--help" ]]; then
  usage
  exit 0
fi

if [[ -z "$INVENTORY_FILE" ]]; then
  usage
  exit 1
fi

if [[ ! -f "$INVENTORY_FILE" ]]; then
  echo "Inventory file not found: $INVENTORY_FILE" >&2
  exit 1
fi

if ! command -v ssh >/dev/null 2>&1; then
  echo "ssh command is required." >&2
  exit 1
fi

if ! command -v scp >/dev/null 2>&1; then
  echo "scp command is required." >&2
  exit 1
fi

if [[ ! -x "${SCRIPT_DIR}/install-linux-agent.sh" ]]; then
  chmod +x "${SCRIPT_DIR}/install-linux-agent.sh"
fi

echo "Starting Linux agent rollout from: $INVENTORY_FILE"
echo "Dry run: $DRY_RUN"

SSH_CMD="$(build_ssh_cmd "ssh")"
SCP_CMD="$(build_ssh_cmd "scp")"

while IFS=',' read -r host user node_id agent_id core_base_url interval services storage_paths containers; do
  host="${host:-}"
  [[ -z "$host" ]] && continue
  [[ "$host" =~ ^# ]] && continue

  user="${user:-root}"
  node_id="${node_id:-}"
  agent_id="${agent_id:-}"
  core_base_url="${core_base_url:-}"
  interval="${interval:-3}"
  services="${services:-docker,ssh,ufw}"
  storage_paths="${storage_paths:-/,/srv,/mnt/storage,/media/storage}"
  containers="${containers:-nextcloud,jellyfin,mariadb,postgres,redis,nginx,traefik,caddy}"

  if [[ -z "$node_id" || -z "$agent_id" || -z "$core_base_url" ]]; then
    echo "Skipping ${host}: missing node_id, agent_id, or core_base_url." >&2
    continue
  fi

  target="${user}@${host}"
  remote_dir="/tmp/hcc-agent-rollout"

  echo "---- ${target} (${node_id}) ----"
  run_cmd $SSH_CMD $SSH_OPTS "$target" "mkdir -p '${remote_dir}'"
  run_cmd $SCP_CMD $SSH_OPTS \
    "${SCRIPT_DIR}/heartbeat_sender.py" \
    "${SCRIPT_DIR}/host_intelligence.py" \
    "${SCRIPT_DIR}/action_runner.py" \
    "${SCRIPT_DIR}/apply-update.sh" \
    "${SCRIPT_DIR}/install-linux-agent.sh" \
    "${SCRIPT_DIR}/hcc-agent.service" \
    "${SCRIPT_DIR}/hcc-agent-update.service" \
    "$target:${remote_dir}/"
  run_cmd $SSH_CMD $SSH_OPTS "$target" "chmod +x '${remote_dir}/install-linux-agent.sh' && if command -v sudo >/dev/null 2>&1; then sudo '${remote_dir}/install-linux-agent.sh' --core-base-url '${core_base_url}' --node-id '${node_id}' --agent-id '${agent_id}' --interval '${interval}' --services '${services}' --storage-paths '${storage_paths}' --containers '${containers}'; else '${remote_dir}/install-linux-agent.sh' --core-base-url '${core_base_url}' --node-id '${node_id}' --agent-id '${agent_id}' --interval '${interval}' --services '${services}' --storage-paths '${storage_paths}' --containers '${containers}'; fi"
  run_cmd $SSH_CMD $SSH_OPTS "$target" "if command -v sudo >/dev/null 2>&1; then sudo systemctl is-active hcc-agent.service && sudo systemctl --no-pager --full status hcc-agent.service || true; else systemctl is-active hcc-agent.service && systemctl --no-pager --full status hcc-agent.service || true; fi"
done < "$INVENTORY_FILE"

echo "Rollout complete."

