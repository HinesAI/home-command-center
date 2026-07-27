#!/usr/bin/env bash
# Remove HCC Terminal services and optionally its installed files.
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
	echo "Run as root: sudo $0 [--purge]" >&2
	exit 1
fi

INSTALL_DIR="${HCC_TERMINAL_INSTALL_DIR:-/opt/hcc-terminal}"
CONFIG_DIR="${HCC_TERMINAL_CONFIG_DIR:-/etc/hcc-terminal}"
STATE_DIR="${HCC_TERMINAL_STATE_DIR:-/var/lib/hcc-terminal}"
PURGE=0
[[ "${1:-}" == "--purge" ]] && PURGE=1

for path in "$INSTALL_DIR" "$CONFIG_DIR" "$STATE_DIR"; do
	case "$path" in
		""|/|/opt|/etc|/var|/usr|/home)
			echo "Refusing unsafe removal path: $path" >&2
			exit 1
			;;
	esac
done

systemctl disable --now \
	hcc-terminal.service \
	hcc-terminal-collect.timer \
	hcc-terminal-report.timer 2>/dev/null || true
rm -f \
	/etc/systemd/system/hcc-terminal.service \
	/etc/systemd/system/hcc-terminal-collect.service \
	/etc/systemd/system/hcc-terminal-collect.timer \
	/etc/systemd/system/hcc-terminal-report.service \
	/etc/systemd/system/hcc-terminal-report.timer
systemctl daemon-reload
systemctl enable --now getty@tty1.service 2>/dev/null || true

rm -rf "$INSTALL_DIR"
if (( PURGE == 1 )); then
	rm -rf "$CONFIG_DIR" "$STATE_DIR"
	echo "HCC Terminal and its configuration/state were removed."
else
	echo "HCC Terminal removed; configuration and state were preserved."
	echo "  Configuration: $CONFIG_DIR"
	echo "  Runtime state: $STATE_DIR"
fi
