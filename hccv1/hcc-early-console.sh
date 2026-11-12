#!/usr/bin/env bash
# Early tty1 hold until hcc-dashboard takes over.
# Lives on rootfs so it can run before Backup_Pool is mounted.
# IMPORTANT: start dashboard --no-block then exit immediately so we release
# tty1. Calling a blocking systemctl start while we hold the TTY deadlocks.
set -uo pipefail

TTY_DEV="${HCC_TTY:-/dev/tty1}"
DASH_UNIT="${HCC_DASHBOARD_UNIT:-hcc-dashboard.service}"
DASH_SCRIPT="${HCC_DASHBOARD_SCRIPT:-/Backup_Pool/scripts/hines-command-center-dashboard.sh}"
export TERM=linux

paint() {
	printf "\033[?25l\033[H\033[2J\033[3J"
	printf "\n"
	printf "  HINES COMMAND CENTER\n"
	printf "  ────────────────────\n"
	printf "  system boot in progress\n"
	printf "\n"
	printf "  [%s] waiting for HCC console\n" "$1"
	printf "  (recovery shell: Ctrl+Alt+F2)\n"
}

if [[ -w "$TTY_DEV" ]]; then
	exec >"$TTY_DEV" 2>/dev/null
fi

frame=0
while true; do
	case $((frame % 4)) in
		0) spin="|" ;;
		1) spin="/" ;;
		2) spin="-" ;;
		3) spin="\\" ;;
	esac
	paint "$spin"

	if [[ -x "$DASH_SCRIPT" ]]; then
		# Release tty before dashboard acquires it — never block here.
		systemctl start --no-block "$DASH_UNIT" </dev/null >/dev/null 2>&1 || true
		exit 0
	fi
	frame=$((frame + 1))
	sleep 0.4
done
