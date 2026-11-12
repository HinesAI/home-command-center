#!/usr/bin/env bash
# Manage the HCC playground stack (hcctest.example.local).
#
# Playground code lives in a SEPARATE folder from prod:
#   prod:  .../hccv2
#   play:  .../hccv2-play
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROD_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
PLAY_ROOT="${HCC_PLAY_ROOT:-$(cd -- "$PROD_ROOT/../hccv2-play" 2>/dev/null && pwd || true)}"
DEPLOY="${PLAY_ROOT}/deploy"
COMPOSE=(docker compose -p hcc-play -f "$DEPLOY/docker-compose.playground.yml" --env-file "$DEPLOY/.env.playground")

usage() {
  cat <<EOF
Usage: hcc-playground.sh <command>

Playground root: ${PLAY_ROOT:-MISSING — set HCC_PLAY_ROOT or create ../hccv2-play}
Prod root:       $PROD_ROOT

  init       Create .env.playground (from prod .env) if missing; sync tree optional
  sync-from-prod  Refresh hccv2-play code from prod tree (keeps play .env + data)
  up         Start playground Core + Web
  down       Stop playground (keeps data volume)
  destroy    Stop and delete playground data volume
  status     Containers + health
  logs       Tail logs
  lab-agent  Start optional lab agent
  paths      Show which folders prod vs play use

URL: http://hcctest.example.local  or  http://127.0.0.1:3001
EOF
}

require_play_root() {
  if [[ -z "${PLAY_ROOT:-}" || ! -d "$PLAY_ROOT/apps" ]]; then
    echo "error: playground tree not found at ../hccv2-play" >&2
    echo "Create it with: rsync -a --exclude .git --exclude dist --exclude var $PROD_ROOT/ $PROD_ROOT/../hccv2-play/" >&2
    exit 1
  fi
}

ensure_env() {
  require_play_root
  if [[ ! -f "$DEPLOY/.env.playground" ]]; then
    echo "error: missing $DEPLOY/.env.playground — run: $0 init" >&2
    exit 1
  fi
}

cmd_paths() {
  echo "Prod code:  $PROD_ROOT"
  echo "Play code:  ${PLAY_ROOT:-unset}"
  echo
  echo "Prod mounts (live):"
  docker inspect deploy-core-1 --format '{{range .Mounts}}{{if eq .Destination "/app"}}{{.Source}}{{end}}{{end}}' 2>/dev/null || echo "  (prod core not running)"
  echo "Play mounts (live):"
  docker inspect hcc-play-core-1 --format '{{range .Mounts}}{{if eq .Destination "/app"}}{{.Source}}{{end}}{{end}}' 2>/dev/null || echo "  (play core not running)"
}

cmd_init() {
  require_play_root
  if [[ -f "$DEPLOY/.env.playground" ]]; then
    echo ".env.playground already exists in play tree"
    return 0
  fi
  if [[ -f "$PROD_ROOT/deploy/.env" ]]; then
    cp "$PROD_ROOT/deploy/.env" "$DEPLOY/.env.playground"
    python3 - <<'PY' "$DEPLOY/.env.playground"
from pathlib import Path
import sys
path = Path(sys.argv[1])
lines = []
seen_origin = False
for line in path.read_text(encoding="utf-8").splitlines():
    if line.startswith("HCC_WEB_ORIGIN="):
        lines.append("HCC_WEB_ORIGIN=http://hcctest.example.local,http://127.0.0.1:3001,http://192.168.1.10:3001")
        seen_origin = True
    elif line.startswith("HCC_PRODUCT_NAME="):
        lines.append("HCC_PRODUCT_NAME=Home Command Center (Test)")
    elif line.startswith("HCC_RELEASE_CHANNEL="):
        lines.append("HCC_RELEASE_CHANNEL=playground")
    else:
        lines.append(line)
if not seen_origin:
    lines.append("HCC_WEB_ORIGIN=http://hcctest.example.local,http://127.0.0.1:3001,http://192.168.1.10:3001")
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
    echo "Created play .env.playground from prod .env"
  else
    cp "$DEPLOY/.env.playground.example" "$DEPLOY/.env.playground"
    echo "Created play .env.playground from example"
  fi
}

cmd_sync_from_prod() {
  require_play_root
  echo "Syncing code from prod → play (excluding .env, data, git, snapshots)..."
  rsync -a \
    --exclude '.git/' \
    --exclude 'dist/' \
    --exclude 'var/' \
    --exclude 'deploy/.env' \
    --exclude 'deploy/.env.playground' \
    --exclude '**/__pycache__/' \
    --exclude '.cursor/' \
    --exclude 'PLAYGROUND-ROOT.md' \
    "$PROD_ROOT/" "$PLAY_ROOT/"
  echo "Done. Play data volume and .env.playground were not overwritten."
}

cmd_up() {
  ensure_env
  "${COMPOSE[@]}" up -d core web
  echo
  echo "Playground started from: $PLAY_ROOT"
  echo "  http://hcctest.example.local"
  echo "  http://127.0.0.1:3001  (API :18081)"
  echo "Prod still mounts: $PROD_ROOT"
}

cmd_down() {
  ensure_env
  "${COMPOSE[@]}" down
  echo "Playground stopped (volume kept)."
}

cmd_destroy() {
  ensure_env
  echo "Deletes playground containers AND hcc-play-core-data volume."
  read -r -p "Type DESTROY to confirm: " confirm
  [[ "$confirm" == "DESTROY" ]] || { echo "aborted"; exit 1; }
  "${COMPOSE[@]}" down -v
  echo "Playground destroyed."
}

cmd_status() {
  require_play_root
  docker compose -p hcc-play -f "$DEPLOY/docker-compose.playground.yml" ps 2>/dev/null || true
  echo
  curl -sf http://127.0.0.1:18081/healthz >/dev/null && echo "core:18081 healthz OK" || echo "core:18081 not reachable"
  curl -sf -o /dev/null http://127.0.0.1:3001/ && echo "web:3001 OK" || echo "web:3001 not reachable"
  echo
  cmd_paths
}

cmd_logs() {
  ensure_env
  "${COMPOSE[@]}" logs -f --tail=100
}

cmd_lab_agent() {
  ensure_env
  "${COMPOSE[@]}" --profile lab-agent up -d agent
  echo "Lab agent agent-play-01 started."
}

case "${1:-}" in
  init) cmd_init ;;
  sync-from-prod) cmd_sync_from_prod ;;
  up) cmd_up ;;
  down) cmd_down ;;
  destroy) cmd_destroy ;;
  status) cmd_status ;;
  logs) cmd_logs ;;
  lab-agent) cmd_lab_agent ;;
  paths) cmd_paths ;;
  ""|-h|--help) usage ;;
  *) echo "unknown command: $1" >&2; usage; exit 1 ;;
esac
