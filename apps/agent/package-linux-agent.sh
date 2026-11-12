#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
OUTPUT="${1:-${SCRIPT_DIR}/../web/downloads/hcc-agent-linux.tar.gz}"

# Prefer live step-ca export; fall back to bundled copy in this package tree.
CA_SRC="${REPO_ROOT}/deploy/plugins/step-ca/certs/HCC-Local-CA.crt"
if [[ ! -f "$CA_SRC" ]]; then
  CA_SRC="${SCRIPT_DIR}/certs/HCC-Local-CA.crt"
fi
if [[ ! -f "$CA_SRC" ]]; then
  echo "Missing HCC-Local-CA.crt (run deploy/plugins/step-ca/scripts/export-root.sh)" >&2
  exit 1
fi
install -d -m 755 "${SCRIPT_DIR}/certs"
install -m 644 "$CA_SRC" "${SCRIPT_DIR}/certs/HCC-Local-CA.crt"

STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT

mkdir -p "${STAGING}/hcc-agent/certs"
install -m 755 "${SCRIPT_DIR}/heartbeat_sender.py" "${STAGING}/hcc-agent/heartbeat_sender.py"
install -m 644 "${SCRIPT_DIR}/host_intelligence.py" "${STAGING}/hcc-agent/host_intelligence.py"
install -m 644 "${SCRIPT_DIR}/action_runner.py" "${STAGING}/hcc-agent/action_runner.py"
install -m 755 "${SCRIPT_DIR}/apply-update.sh" "${STAGING}/hcc-agent/apply-update.sh"
install -m 755 "${SCRIPT_DIR}/install-ca-trust.sh" "${STAGING}/hcc-agent/install-ca-trust.sh"
install -m 644 "${SCRIPT_DIR}/hcc-agent.service" "${STAGING}/hcc-agent/hcc-agent.service"
install -m 644 "${SCRIPT_DIR}/hcc-agent-update.service" "${STAGING}/hcc-agent/hcc-agent-update.service"
install -m 755 "${SCRIPT_DIR}/install-linux-agent.sh" "${STAGING}/hcc-agent/install-linux-agent.sh"
install -m 755 "${SCRIPT_DIR}/setup-hcc-agent.sh" "${STAGING}/hcc-agent/setup-hcc-agent.sh"
install -m 644 "${SCRIPT_DIR}/certs/HCC-Local-CA.crt" "${STAGING}/hcc-agent/certs/HCC-Local-CA.crt"

mkdir -p "$(dirname "$OUTPUT")"
tar -czf "$OUTPUT" -C "$STAGING" hcc-agent
# Also publish standalone cert for phones / manual install
install -m 644 "${SCRIPT_DIR}/certs/HCC-Local-CA.crt" "${SCRIPT_DIR}/../web/downloads/HCC-Local-CA.crt"
echo "Created package: $OUTPUT"
sha256sum "$OUTPUT"
