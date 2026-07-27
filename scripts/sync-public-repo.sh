#!/usr/bin/env bash
# Sync shared Home Command Center platform paths into another repository checkout.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
TARGET="${1:-}"

usage() {
  cat <<'EOF'
Usage: sync-public-repo.sh <target-repo-path>

Copy shared platform directories and release files from the current checkout
into another git working tree (for example ../home-command-center).

Internal-only files are excluded automatically. Review and commit changes in
the target repository before pushing.
EOF
}

if [[ -z "$TARGET" ]]; then
  usage
  exit 1
fi

TARGET="$(cd -- "$TARGET" && pwd)"

if [[ ! -d "$TARGET/.git" ]]; then
  echo "error: target is not a git repository: $TARGET" >&2
  exit 1
fi

RSYNC_EXCLUDES=(
  --exclude '.git/'
  --exclude '.cursor/'
  --exclude 'dist/'
  --exclude 'deploy/.env'
  --exclude 'deploy/Caddyfile'
  --exclude 'deploy/DNS-hcc.web-flip.local.md'
  --exclude 'deploy/hcc.env.internal.example'
  --exclude 'docs/INTERNAL-HINES.md'
  --exclude '**/__pycache__/'
  --exclude '**/*.pyc'
  --exclude 'apps/core/data/'
  --exclude 'apps/terminal/var/'
)

SHARED_PATHS=(
  apps/core
  apps/agent
  apps/agent-windows
  apps/terminal
  apps/web
  contracts
  scripts
  deploy/Caddyfile.prod
  deploy/docker-compose.dev.yml
  deploy/docker-compose.prod.yml
  deploy/hcc.env.prod.example
  deploy/install-hcc.sh
  deploy/PACKAGE-README.md
  docs/ARCHITECTURE.md
  docs/AGENT-IDENTITY.md
  docs/DASHBOARD-FRONTEND-BRIEF.md
  docs/REPOSITORIES.md
  VERSION
  CHANGELOG.md
  README.md
  .dockerignore
)

echo "Syncing shared platform paths from:"
echo "  $ROOT"
echo "into:"
echo "  $TARGET"
echo

for rel_path in "${SHARED_PATHS[@]}"; do
  src="$ROOT/$rel_path"
  if [[ ! -e "$src" ]]; then
    echo "skip missing: $rel_path"
    continue
  fi
  dest_parent="$(dirname -- "$TARGET/$rel_path")"
  mkdir -p "$dest_parent"
  rsync -a --delete "${RSYNC_EXCLUDES[@]}" "$src" "$dest_parent/"
  echo "synced: $rel_path"
done

cat <<EOF

Done. Next steps in the target repo:
  cd "$TARGET"
  git status
  git add -A
  git commit -m "Sync platform changes"
  git push
EOF
