#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT="${1:-${SCRIPT_DIR}/../web/downloads/hcc-agent-linux.tar.gz}"

STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT

mkdir -p "${STAGING}/hcc-agent"
install -m 755 "${SCRIPT_DIR}/heartbeat_sender.py" "${STAGING}/hcc-agent/heartbeat_sender.py"
install -m 644 "${SCRIPT_DIR}/host_intelligence.py" "${STAGING}/hcc-agent/host_intelligence.py"
install -m 644 "${SCRIPT_DIR}/action_runner.py" "${STAGING}/hcc-agent/action_runner.py"
install -m 755 "${SCRIPT_DIR}/apply-update.sh" "${STAGING}/hcc-agent/apply-update.sh"
install -m 644 "${SCRIPT_DIR}/hcc-agent.service" "${STAGING}/hcc-agent/hcc-agent.service"
install -m 644 "${SCRIPT_DIR}/hcc-agent-update.service" "${STAGING}/hcc-agent/hcc-agent-update.service"
install -m 755 "${SCRIPT_DIR}/install-linux-agent.sh" "${STAGING}/hcc-agent/install-linux-agent.sh"
install -m 755 "${SCRIPT_DIR}/setup-hcc-agent.sh" "${STAGING}/hcc-agent/setup-hcc-agent.sh"

mkdir -p "$(dirname "$OUTPUT")"
tar -czf "$OUTPUT" -C "$STAGING" hcc-agent
echo "Created package: $OUTPUT"
sha256sum "$OUTPUT"
