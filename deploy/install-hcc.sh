#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VERSION_FILE="$SCRIPT_DIR/VERSION"
[[ -f "$VERSION_FILE" ]] || VERSION_FILE="$SCRIPT_DIR/../VERSION"
VERSION="$(tr -d '[:space:]' <"$VERSION_FILE")"
INSTALL_ROOT="/opt/hcc"
CONFIG_DIR="/etc/hcc"
HOSTNAME_VALUE="hcc.web-flip.local"
BIND_ADDRESS="0.0.0.0"
HTTP_PORT="80"
START_STACK=1
INSTALL_DOCKER=1

usage() {
  cat <<'EOF'
Usage: sudo ./install-hcc.sh [options]

Options:
  --hostname NAME        Internal DNS name (default: hcc.web-flip.local)
  --bind ADDRESS         LAN address to bind, or 0.0.0.0 (default)
  --port PORT            HTTP port (default: 80)
  --install-root PATH    Release root (default: /opt/hcc)
  --config-dir PATH      Persistent configuration (default: /etc/hcc)
  --no-install-docker    Fail instead of installing Docker when absent
  --no-start             Install and load images without starting HCC
  -h, --help             Show this help
EOF
}

while (($#)); do
  case "$1" in
    --hostname) HOSTNAME_VALUE="${2:?missing hostname}"; shift 2 ;;
    --bind) BIND_ADDRESS="${2:?missing bind address}"; shift 2 ;;
    --port) HTTP_PORT="${2:?missing port}"; shift 2 ;;
    --install-root) INSTALL_ROOT="${2:?missing install root}"; shift 2 ;;
    --config-dir) CONFIG_DIR="${2:?missing config directory}"; shift 2 ;;
    --no-install-docker) INSTALL_DOCKER=0; shift ;;
    --no-start) START_STACK=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ $EUID -ne 0 ]]; then
  echo "Run this installer as root: sudo ./install-hcc.sh" >&2
  exit 1
fi

if [[ ! "$HOSTNAME_VALUE" =~ ^[A-Za-z0-9.-]+$ ]]; then
  echo "Invalid hostname: $HOSTNAME_VALUE" >&2
  exit 2
fi
if [[ ! "$HTTP_PORT" =~ ^[0-9]+$ ]] || ((HTTP_PORT < 1 || HTTP_PORT > 65535)); then
  echo "Invalid HTTP port: $HTTP_PORT" >&2
  exit 2
fi

install_docker() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    return
  fi
  if ((INSTALL_DOCKER == 0)); then
    echo "Docker Engine with Compose v2 is required." >&2
    exit 1
  fi
  if ! command -v apt-get >/dev/null 2>&1; then
    echo "Automatic Docker installation is supported only on Ubuntu/Debian." >&2
    exit 1
  fi

  echo "Installing Docker Engine and Compose..."
  apt-get update
  if ! DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io docker-compose-v2; then
    DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io docker-compose-plugin
  fi
  systemctl enable --now docker
  docker compose version >/dev/null
}

random_hex() {
  local bytes="${1:-24}"
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex "$bytes"
  else
    od -An -N "$bytes" -tx1 /dev/urandom | tr -d ' \n'
  fi
}

install_docker

RELEASE_DIR="$INSTALL_ROOT/releases/$VERSION"
CURRENT_LINK="$INSTALL_ROOT/current"
COMPOSE_ENV="$CONFIG_DIR/compose.env"
RUNTIME_ENV="$CONFIG_DIR/hcc.env"

install -d -m 0755 "$RELEASE_DIR" "$CONFIG_DIR"
install -m 0644 "$SCRIPT_DIR/compose.yml" "$RELEASE_DIR/compose.yml"
install -m 0644 "$SCRIPT_DIR/Caddyfile.prod" "$RELEASE_DIR/Caddyfile.prod"
install -m 0644 "$SCRIPT_DIR/VERSION" "$RELEASE_DIR/VERSION"

INITIAL_PASSWORD=""
if [[ ! -f "$RUNTIME_ENV" ]]; then
  AUTH_SECRET="$(random_hex 32)"
  INITIAL_PASSWORD="$(random_hex 12)"
  sed \
    -e "s/__HCC_AUTH_SECRET__/$AUTH_SECRET/g" \
    -e "s/__HCC_LOCAL_ADMIN_PASSWORD__/$INITIAL_PASSWORD/g" \
    -e "s/__HCC_HOSTNAME__/$HOSTNAME_VALUE/g" \
    "$SCRIPT_DIR/hcc.env.example" >"$RUNTIME_ENV"
  chmod 0600 "$RUNTIME_ENV"
fi

cat >"$COMPOSE_ENV" <<EOF
HCC_VERSION=$VERSION
HCC_RELEASE_CHANNEL=stable
HCC_CONFIG_FILE=$RUNTIME_ENV
HCC_BIND_ADDRESS=$BIND_ADDRESS
HCC_HTTP_PORT=$HTTP_PORT
EOF
chmod 0600 "$COMPOSE_ENV"

ln -sfn "$RELEASE_DIR" "$CURRENT_LINK"

if [[ -f "$SCRIPT_DIR/images/hcc-images.tar.gz" ]]; then
  echo "Loading bundled container images..."
  gzip -dc "$SCRIPT_DIR/images/hcc-images.tar.gz" | docker load
else
  echo "Bundled image archive is missing." >&2
  exit 1
fi

if ((START_STACK == 1)); then
  echo "Starting HCC $VERSION..."
  docker compose --env-file "$COMPOSE_ENV" -f "$CURRENT_LINK/compose.yml" up -d

  CHECK_HOST="$BIND_ADDRESS"
  [[ "$CHECK_HOST" == "0.0.0.0" ]] && CHECK_HOST="127.0.0.1"
  HEALTH_URL="http://${CHECK_HOST}:${HTTP_PORT}/healthz"
  healthy=0
  for _attempt in $(seq 1 30); do
    if command -v curl >/dev/null 2>&1; then
      curl -fsS "$HEALTH_URL" >/dev/null 2>&1 && healthy=1 && break
    elif command -v wget >/dev/null 2>&1; then
      wget -q -O /dev/null "$HEALTH_URL" && healthy=1 && break
    fi
    sleep 2
  done
  if ((healthy == 0)); then
    echo "HCC started, but the health check did not pass: $HEALTH_URL" >&2
    docker compose --env-file "$COMPOSE_ENV" -f "$CURRENT_LINK/compose.yml" ps
    exit 1
  fi
fi

echo
echo "HCC $VERSION installed successfully."
echo "Dashboard: http://${HOSTNAME_VALUE}:${HTTP_PORT}"
echo "Configuration: $RUNTIME_ENV"
echo "Release: $RELEASE_DIR"
if [[ -n "$INITIAL_PASSWORD" ]]; then
  echo
  echo "Initial local administrator: hccadmin"
  echo "Initial local password: $INITIAL_PASSWORD"
  echo "Save this password, then change it in $RUNTIME_ENV."
fi
echo
echo "Create or update internal DNS so $HOSTNAME_VALUE resolves to this server."
echo "Restrict port $HTTP_PORT to your LAN and VPN networks with the host firewall."
