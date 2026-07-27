#!/usr/bin/env bash
# Install HCC Terminal as the full-screen tty1 dashboard.
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
	echo "Run as root: sudo $0 [--no-start]" >&2
	exit 1
fi

SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${HCC_TERMINAL_INSTALL_DIR:-/opt/hcc-terminal}"
CONFIG_DIR="${HCC_TERMINAL_CONFIG_DIR:-/etc/hcc-terminal}"
STATE_DIR="${HCC_TERMINAL_STATE_DIR:-/var/lib/hcc-terminal}"
START=1

for path in "$INSTALL_DIR" "$CONFIG_DIR" "$STATE_DIR"; do
	case "$path" in
		""|/|/opt|/etc|/var|/usr|/home)
			echo "Refusing unsafe installation path: $path" >&2
			exit 1
			;;
	esac
done

for arg in "$@"; do
	case "$arg" in
		--no-start) START=0 ;;
		*)
			echo "Unknown argument: $arg" >&2
			exit 2
			;;
	esac
done

missing=()
for command in awk bash curl flock free getent install ip jq ping python3 sed ss systemctl; do
	command -v "$command" >/dev/null 2>&1 || missing+=("$command")
done
if (( ${#missing[@]} > 0 )); then
	echo "Missing required commands: ${missing[*]}" >&2
	echo "Install them with your operating system package manager, then retry." >&2
	exit 1
fi

install -d -m 0755 "$INSTALL_DIR/bin" "$INSTALL_DIR/assets"
install -d -m 0755 "$CONFIG_DIR" "$STATE_DIR"
install -m 0755 "$SOURCE_DIR"/bin/* "$INSTALL_DIR/bin/"
install -m 0644 "$SOURCE_DIR/assets/startup.wav" "$INSTALL_DIR/assets/startup.wav"

for config in hcc-network.targets hcc-docker.watch hcc-proxmox.nodes; do
	if [[ ! -e "$CONFIG_DIR/$config" ]]; then
		install -m 0644 "$SOURCE_DIR/config/$config" "$CONFIG_DIR/$config"
	fi
done
for example in "$SOURCE_DIR"/config/*.env.example; do
	install -m 0644 "$example" "$CONFIG_DIR/$(basename "$example")"
done
if [[ ! -e "$CONFIG_DIR/hcc-terminal.env" ]]; then
	install -m 0644 \
		"$SOURCE_DIR/config/hcc-terminal.env.example" \
		"$CONFIG_DIR/hcc-terminal.env"
fi

render_unit() {
	local source=$1 target=$2
	sed \
		-e "s|@INSTALL_DIR@|$INSTALL_DIR|g" \
		-e "s|@CONFIG_DIR@|$CONFIG_DIR|g" \
		-e "s|@STATE_DIR@|$STATE_DIR|g" \
		"$source" > "$target"
	chmod 0644 "$target"
}

render_unit \
	"$SOURCE_DIR/systemd/hcc-terminal.service.in" \
	/etc/systemd/system/hcc-terminal.service
render_unit \
	"$SOURCE_DIR/systemd/hcc-terminal-collect.service.in" \
	/etc/systemd/system/hcc-terminal-collect.service
render_unit \
	"$SOURCE_DIR/systemd/hcc-terminal-report.service.in" \
	/etc/systemd/system/hcc-terminal-report.service
install -m 0644 \
	"$SOURCE_DIR/systemd/hcc-terminal-collect.timer" \
	/etc/systemd/system/hcc-terminal-collect.timer
install -m 0644 \
	"$SOURCE_DIR/systemd/hcc-terminal-report.timer" \
	/etc/systemd/system/hcc-terminal-report.timer

"$INSTALL_DIR/bin/generate-banners.py" "$STATE_DIR"
HCC_TERMINAL_APP_ROOT="$INSTALL_DIR" \
HCC_TERMINAL_CONFIG_DIR="$CONFIG_DIR" \
HCC_TERMINAL_STATE_DIR="$STATE_DIR" \
	"$INSTALL_DIR/bin/hcc-collect-status"

systemctl daemon-reload
if (( START == 1 )); then
	systemctl disable --now getty@tty1.service 2>/dev/null || true
	systemctl enable --now hcc-terminal.service
	systemctl enable --now hcc-terminal-collect.timer
	if [[ -f "$CONFIG_DIR/hcc-email.env" ]]; then
		systemctl enable --now hcc-terminal-report.timer
	fi
fi

echo
echo "HCC Terminal installed."
echo "  Application: $INSTALL_DIR"
echo "  Configuration: $CONFIG_DIR"
echo "  Runtime state: $STATE_DIR"
if (( START == 1 )); then
	echo "  Dashboard: tty1"
else
	echo "  Services were installed but not enabled (--no-start)."
fi
