#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
VERSION="$(tr -d '[:space:]' <"$ROOT/VERSION")"
PLATFORM="${HCC_PLATFORM:-linux/amd64}"
ARCH_LABEL="${PLATFORM//\//-}"
OUTPUT_DIR="${HCC_OUTPUT_DIR:-$ROOT/dist}"
PACKAGE_NAME="hcc-v${VERSION}-${ARCH_LABEL}"
STAGING_ROOT="$OUTPUT_DIR/.staging"
PACKAGE_ROOT="$STAGING_ROOT/$PACKAGE_NAME"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required to build the HCC package." >&2
  exit 1
fi

rm -rf "$PACKAGE_ROOT"
mkdir -p "$PACKAGE_ROOT/images" "$PACKAGE_ROOT/clients" "$OUTPUT_DIR"
trap 'rm -rf "$STAGING_ROOT"' EXIT

echo "Building HCC Core $VERSION for $PLATFORM..."
docker build \
  --platform "$PLATFORM" \
  --file "$ROOT/apps/core/Dockerfile" \
  --tag "hcc-core:$VERSION" \
  "$ROOT"

echo "Building HCC Web $VERSION for $PLATFORM..."
docker build \
  --platform "$PLATFORM" \
  --file "$ROOT/apps/web/Dockerfile" \
  --tag "hcc-web:$VERSION" \
  "$ROOT"

echo "Fetching Caddy runtime..."
docker pull --platform "$PLATFORM" caddy:2.8-alpine

echo "Exporting container images..."
docker save "hcc-core:$VERSION" "hcc-web:$VERSION" caddy:2.8-alpine \
  | gzip -9 >"$PACKAGE_ROOT/images/hcc-images.tar.gz"

install -m 0755 "$ROOT/deploy/install-hcc.sh" "$PACKAGE_ROOT/install-hcc.sh"
install -m 0644 "$ROOT/deploy/docker-compose.prod.yml" "$PACKAGE_ROOT/compose.yml"
install -m 0644 "$ROOT/deploy/Caddyfile.prod" "$PACKAGE_ROOT/Caddyfile.prod"
install -m 0600 "$ROOT/deploy/hcc.env.prod.example" "$PACKAGE_ROOT/hcc.env.example"
install -m 0644 "$ROOT/deploy/PACKAGE-README.md" "$PACKAGE_ROOT/README.md"
install -m 0644 "$ROOT/VERSION" "$PACKAGE_ROOT/VERSION"

tar -C "$ROOT" -czf "$PACKAGE_ROOT/clients/hcc-terminal-v${VERSION}.tar.gz" apps/terminal
tar -C "$ROOT" -czf "$PACKAGE_ROOT/clients/hcc-linux-agent-v${VERSION}.tar.gz" apps/agent

(
  cd "$PACKAGE_ROOT"
  sha256sum \
    Caddyfile.prod \
    README.md \
    VERSION \
    compose.yml \
    hcc.env.example \
    images/hcc-images.tar.gz \
    clients/*.tar.gz \
    >SHA256SUMS
)

tar -C "$STAGING_ROOT" -czf "$OUTPUT_DIR/$PACKAGE_NAME.tar.gz" "$PACKAGE_NAME"
sha256sum "$OUTPUT_DIR/$PACKAGE_NAME.tar.gz" >"$OUTPUT_DIR/$PACKAGE_NAME.tar.gz.sha256"

echo
echo "Package created:"
echo "  $OUTPUT_DIR/$PACKAGE_NAME.tar.gz"
echo "  $OUTPUT_DIR/$PACKAGE_NAME.tar.gz.sha256"
