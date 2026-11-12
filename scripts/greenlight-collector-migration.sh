#!/usr/bin/env bash
# Switch integration API endpoints from legacy pulls to collector snapshots.
#
# Default state (no action needed): HCC_SOURCE_*=legacy — dashboard uses existing
# integrations.py paths. Background collectors run for staging only.
#
# Phases:
#   legacy          API uses integrations.py only (default)
#   collector       API prefers collector snapshot, falls back to legacy
#   collector-only  API uses collector snapshot only; legacy API pulls disabled
#
# This script applies collector-only for the selected services after greenlight.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="${HCC_ENV_FILE:-$ROOT/deploy/.env}"
SERVICES=(weather network security climate)
DRY_RUN=false
RESTART_CORE=false

usage() {
  cat <<'EOF'
Usage: greenlight-collector-migration.sh [options]

Apply collector-only routing for integration APIs and disable legacy API pulls
for those services. Background collectors continue to refresh snapshots.

Options:
  --env-file PATH   Target env file (default: deploy/.env)
  --service NAME    Migrate one service (repeatable). Default: all four.
  --dry-run         Print changes without writing
  --restart-core    Restart deploy-core-1 after updating env
  --help            Show this help

Canary mode (compare collector vs legacy without disabling legacy):
  HCC_SOURCE_weather=collector docker compose ... restart core

Rollback:
  scripts/rollback-collector-migration.sh
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file)
      ENV_FILE="$2"
      shift 2
      ;;
    --service)
      SERVICES=("$2")
      shift 2
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --restart-core)
      RESTART_CORE=true
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ ! -f "$ENV_FILE" ]]; then
  echo "error: env file not found: $ENV_FILE" >&2
  exit 1
fi

upsert_env() {
  local key="$1"
  local value="$2"
  local file="$3"
  if grep -q "^${key}=" "$file"; then
    if $DRY_RUN; then
      echo "update $key=$value"
    else
      sed -i "s|^${key}=.*|${key}=${value}|" "$file"
    fi
  else
    if $DRY_RUN; then
      echo "append $key=$value"
    else
      printf '\n%s=%s\n' "$key" "$value" >>"$file"
    fi
  fi
}

stamp_file="$ROOT/deploy/.collector-migration.json"
timestamp="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

echo "Greenlighting collector migration"
echo "  env file: $ENV_FILE"
echo "  services: ${SERVICES[*]}"

for service in "${SERVICES[@]}"; do
  upper="$(printf '%s' "$service" | tr '[:lower:]' '[:upper:]')"
  upsert_env "HCC_SOURCE_${upper}" "collector-only" "$ENV_FILE"
  upsert_env "HCC_LEGACY_${upper}" "false" "$ENV_FILE"
done

upsert_env "HCC_COLLECTORS_ENABLED" "true" "$ENV_FILE"

if ! $DRY_RUN; then
  mkdir -p "$(dirname -- "$stamp_file")"
  python3 - <<'PY' "$stamp_file" "$timestamp" "${SERVICES[@]}"
import json, sys
path, ts, *services = sys.argv[1:]
payload = {
    "migratedAt": ts,
    "mode": "collector-only",
    "services": services,
}
with open(path, "w", encoding="utf-8") as fh:
    json.dump(payload, fh, indent=2)
    fh.write("\n")
PY
fi

cat <<EOF

Migration flags written. After Core reload:
  curl -s http://127.0.0.1:18080/api/v1/collectors/migration | jq .

Integration APIs now read collector snapshots for: ${SERVICES[*]}
Legacy API pulls for those services are disabled.

Restart Core to apply:
  cd $ROOT/deploy && docker compose -f docker-compose.dev.yml restart core
EOF

if $RESTART_CORE && ! $DRY_RUN; then
  (cd "$ROOT/deploy" && docker compose -f docker-compose.dev.yml restart core)
fi
