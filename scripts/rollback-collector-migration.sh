#!/usr/bin/env bash
# Restore legacy integration API routing for migrated services.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="${HCC_ENV_FILE:-$ROOT/deploy/.env}"
SERVICES=(weather network security climate)
DRY_RUN=false
RESTART_CORE=false

usage() {
  cat <<'EOF'
Usage: rollback-collector-migration.sh [options]

Restore legacy integration API routing (default behavior).

Options:
  --env-file PATH   Target env file (default: deploy/.env)
  --service NAME    Roll back one service (repeatable)
  --dry-run         Print changes without writing
  --restart-core    Restart deploy-core-1 after updating env
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file) ENV_FILE="$2"; shift 2 ;;
    --service) SERVICES=("$2"); shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    --restart-core) RESTART_CORE=true; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage; exit 1 ;;
  esac
done

[[ -f "$ENV_FILE" ]] || { echo "error: env file not found: $ENV_FILE" >&2; exit 1; }

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

echo "Rolling back collector migration for: ${SERVICES[*]}"

for service in "${SERVICES[@]}"; do
  upper="$(printf '%s' "$service" | tr '[:lower:]' '[:upper:]')"
  upsert_env "HCC_SOURCE_${upper}" "legacy" "$ENV_FILE"
  upsert_env "HCC_LEGACY_${upper}" "true" "$ENV_FILE"
done

stamp_file="$ROOT/deploy/.collector-migration.json"
if ! $DRY_RUN && [[ -f "$stamp_file" ]]; then
  rm -f "$stamp_file"
fi

echo "Legacy integration routing restored. Restart Core to apply."

if $RESTART_CORE && ! $DRY_RUN; then
  (cd "$ROOT/deploy" && docker compose -f docker-compose.dev.yml restart core)
fi
