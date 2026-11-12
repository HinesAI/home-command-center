#!/usr/bin/env bash
# Install HCC Local CA into the system trust store (idempotent).
# Usage: sudo ./install-ca-trust.sh [cert.crt] [/opt/hcc-agent]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CERT="${1:-${SCRIPT_DIR}/certs/HCC-Local-CA.crt}"
INSTALL_DIR="${2:-/opt/hcc-agent}"

if [[ ! -f "$CERT" ]]; then
  echo "HCC CA cert not found: $CERT (skipping trust install)" >&2
  exit 0
fi

install -d -m 755 "${INSTALL_DIR}/certs"
install -m 644 "$CERT" "${INSTALL_DIR}/certs/HCC-Local-CA.crt"

if [[ -d /usr/local/share/ca-certificates ]]; then
  install -m 644 "$CERT" /usr/local/share/ca-certificates/HCC-Local-CA.crt
  if command -v update-ca-certificates >/dev/null 2>&1; then
    update-ca-certificates >/dev/null
  fi
  echo "Installed HCC Local CA into Debian/Ubuntu trust store."
elif [[ -d /etc/pki/ca-trust/source/anchors ]]; then
  install -m 644 "$CERT" /etc/pki/ca-trust/source/anchors/HCC-Local-CA.crt
  if command -v update-ca-trust >/dev/null 2>&1; then
    update-ca-trust extract >/dev/null
  fi
  echo "Installed HCC Local CA into RHEL/CentOS trust store."
else
  echo "No known system CA directory; cert kept at ${INSTALL_DIR}/certs/HCC-Local-CA.crt" >&2
fi
