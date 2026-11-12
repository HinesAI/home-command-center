#!/usr/bin/env bash
# Snapshot / restore HCC Core data volumes (prod or playground).
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
SNAPSHOT_ROOT="${HCC_SNAPSHOT_DIR:-$ROOT/var/snapshots}"

usage() {
  cat <<'EOF'
Usage: hcc-snapshot.sh <target> <command> [args]

Targets:
  prod         Volume: deploy_hcc-core-data  (live fleet — be careful)
  playground   Volume: hcc-play_hcc-play-core-data

Commands:
  create [--label NAME]   Snapshot volume + env overlay
  list                    List snapshots for target
  restore <label|path>    Restore snapshot into target volume (stops Core briefly)
  seed-from prod          Copy latest prod snapshot into playground volume

Examples:
  ./scripts/hcc-snapshot.sh playground create --label before-ha
  ./scripts/hcc-snapshot.sh playground restore before-ha
  ./scripts/hcc-snapshot.sh playground seed-from prod
EOF
}

target_config() {
  case "$1" in
    prod)
      VOLUME="deploy_hcc-core-data"
      ENV_FILE="$ROOT/deploy/.env"
      COMPOSE_PROJECT="deploy"
      COMPOSE_FILE="$ROOT/deploy/docker-compose.dev.yml"
      CORE_SERVICE="core"
      ;;
    playground|play|hcctest)
      VOLUME="hcc-play_hcc-play-core-data"
      ENV_FILE="$ROOT/deploy/.env.playground"
      COMPOSE_PROJECT="hcc-play"
      COMPOSE_FILE="$ROOT/deploy/docker-compose.playground.yml"
      CORE_SERVICE="core"
      ;;
    *)
      echo "unknown target: $1" >&2
      usage
      exit 1
      ;;
  esac
}

require_volume() {
  if ! docker volume inspect "$VOLUME" >/dev/null 2>&1; then
    echo "error: volume not found: $VOLUME" >&2
    echo "Start the stack once so the volume exists." >&2
    exit 1
  fi
}

cmd_create() {
  local label="${LABEL:-$(date -u +%Y%m%dT%H%M%SZ)}"
  local dest="$SNAPSHOT_ROOT/$TARGET/$label"
  mkdir -p "$dest"
  require_volume

  echo "Snapshotting $VOLUME → $dest"
  docker run --rm \
    -v "$VOLUME:/data:ro" \
    -v "$dest:/backup" \
    alpine:3.20 \
    tar -C /data -czf /backup/core-data.tar.gz .

  if [[ -f "$ENV_FILE" ]]; then
    cp "$ENV_FILE" "$dest/env.overlay"
  fi

  cat >"$dest/manifest.json" <<EOF
{
  "target": "$TARGET",
  "volume": "$VOLUME",
  "label": "$label",
  "createdAt": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "host": "$(hostname -f 2>/dev/null || hostname)"
}
EOF
  echo "Created snapshot: $label"
  echo "  $dest"
}

cmd_list() {
  local dir="$SNAPSHOT_ROOT/$TARGET"
  if [[ ! -d "$dir" ]]; then
    echo "No snapshots for $TARGET"
    return 0
  fi
  find "$dir" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort
}

stop_core() {
  if docker compose -p "$COMPOSE_PROJECT" -f "$COMPOSE_FILE" ps --status running 2>/dev/null | grep -q "$CORE_SERVICE"; then
    docker compose -p "$COMPOSE_PROJECT" -f "$COMPOSE_FILE" stop "$CORE_SERVICE" >/dev/null
    CORE_WAS_RUNNING=1
  else
    CORE_WAS_RUNNING=0
  fi
}

start_core() {
  if [[ "${CORE_WAS_RUNNING:-0}" == "1" ]]; then
    if [[ "$TARGET" == "playground" || "$TARGET" == "play" || "$TARGET" == "hcctest" ]]; then
      docker compose -p "$COMPOSE_PROJECT" -f "$COMPOSE_FILE" --env-file "$ENV_FILE" start "$CORE_SERVICE" >/dev/null || \
        docker compose -p "$COMPOSE_PROJECT" -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d "$CORE_SERVICE" >/dev/null
    else
      docker compose -p "$COMPOSE_PROJECT" -f "$COMPOSE_FILE" start "$CORE_SERVICE" >/dev/null || \
        docker compose -p "$COMPOSE_PROJECT" -f "$COMPOSE_FILE" up -d "$CORE_SERVICE" >/dev/null
    fi
  fi
}

resolve_snapshot_dir() {
  local arg="$1"
  if [[ -d "$arg" ]]; then
    SNAP_DIR="$arg"
  elif [[ -d "$SNAPSHOT_ROOT/$TARGET/$arg" ]]; then
    SNAP_DIR="$SNAPSHOT_ROOT/$TARGET/$arg"
  else
    echo "error: snapshot not found: $arg" >&2
    exit 1
  fi
  [[ -f "$SNAP_DIR/core-data.tar.gz" ]] || { echo "error: missing core-data.tar.gz in $SNAP_DIR" >&2; exit 1; }
}

cmd_restore() {
  local arg="${1:-}"
  [[ -n "$arg" ]] || { echo "error: restore requires label or path" >&2; exit 1; }
  resolve_snapshot_dir "$arg"
  require_volume

  echo "Restoring $SNAP_DIR → $VOLUME"
  if [[ "$TARGET" == "prod" ]]; then
    read -r -p "Confirm restore into PROD volume (type RESTORE): " confirm
    [[ "$confirm" == "RESTORE" ]] || { echo "aborted"; exit 1; }
  fi

  stop_core
  docker run --rm \
    -v "$VOLUME:/data" \
    -v "$SNAP_DIR:/backup:ro" \
    alpine:3.20 \
    sh -c 'rm -rf /data/* /data/.[!.]* /data/..?* 2>/dev/null; tar -C /data -xzf /backup/core-data.tar.gz'
  start_core
  echo "Restore complete."
}

cmd_seed_from_prod() {
  [[ "$TARGET" == "playground" || "$TARGET" == "play" || "$TARGET" == "hcctest" ]] || {
    echo "error: seed-from only valid for playground target" >&2
    exit 1
  }
  local prod_latest
  prod_latest="$(find "$SNAPSHOT_ROOT/prod" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -1 | awk '{print $2}')"
  if [[ -z "$prod_latest" ]]; then
    echo "No prod snapshots yet — creating one first..."
    TARGET=prod target_config prod
    LABEL="seed-$(date -u +%Y%m%dT%H%M%SZ)" cmd_create
    TARGET=playground target_config playground
    prod_latest="$(find "$SNAPSHOT_ROOT/prod" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -nr | head -1 | awk '{print $2}')"
  fi
  echo "Seeding playground from $prod_latest"
  # Ensure playground volume exists
  if ! docker volume inspect "$VOLUME" >/dev/null 2>&1; then
    docker compose -p hcc-play -f "$ROOT/deploy/docker-compose.playground.yml" --env-file "$ENV_FILE" up -d core
    docker compose -p hcc-play -f "$ROOT/deploy/docker-compose.playground.yml" --env-file "$ENV_FILE" stop core
  fi
  SNAP_DIR="$prod_latest"
  stop_core
  docker run --rm \
    -v "$VOLUME:/data" \
    -v "$SNAP_DIR:/backup:ro" \
    alpine:3.20 \
    sh -c 'rm -rf /data/* /data/.[!.]* /data/..?* 2>/dev/null; tar -C /data -xzf /backup/core-data.tar.gz'
  start_core
  echo "Playground seeded from prod snapshot (fleet state copied). Agents still point at prod unless you change them."
}

TARGET="${1:-}"
CMD="${2:-}"
LABEL=""
shift 2 2>/dev/null || true

while [[ $# -gt 0 ]]; do
  case "$1" in
    --label) LABEL="$2"; shift 2 ;;
    *) break ;;
  esac
done

[[ -n "$TARGET" && -n "$CMD" ]] || { usage; exit 1; }
target_config "$TARGET"

case "$CMD" in
  create) cmd_create ;;
  list) cmd_list ;;
  restore) cmd_restore "${1:-}" ;;
  seed-from)
    [[ "${1:-}" == "prod" ]] || { echo "usage: hcc-snapshot.sh playground seed-from prod" >&2; exit 1; }
    cmd_seed_from_prod
    ;;
  *) usage; exit 1 ;;
esac
