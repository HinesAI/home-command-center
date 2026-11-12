#!/usr/bin/env bash
# Nightly apt updates with HCC console notice on tty1.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
LOCK_FILE="/run/hcc-updates.lock"
LOG_FILE="/var/log/hcc-nightly-updates.log"
REPAINT_SEC="${HCC_UPDATES_REPAINT_SEC:-2}"
COLLECT_SCRIPT="${HCC_STATUS_COLLECT:-$ROOT/collect-hcc-status.sh}"

# shellcheck source=/dev/null
source "$ROOT/hcc-appliance-screen.lib"

painter_pid=""

stop_painter() {
	if declare -F hcc_circle_stop >/dev/null 2>&1; then
		hcc_circle_stop
	fi
	[[ -n "$painter_pid" ]] && kill "$painter_pid" 2>/dev/null || true
	wait "$painter_pid" 2>/dev/null || true
	painter_pid=""
}

cleanup() {
	rm -f "$LOCK_FILE"
	stop_painter
}
trap cleanup EXIT INT TERM

start_painter() {
	# Prefer continuous circular FB spinner with real font lettering.
	if declare -F hcc_circle_start >/dev/null 2>&1 && hcc_circle_start updates --until-file "$LOCK_FILE"; then
		painter_pid="$(cat "${CIRCLE_PID_FILE:-/run/hcc-circle-status.pid}" 2>/dev/null || true)"
		return 0
	fi
	hcc_screen_paint updates
	(
		while [[ -f "$LOCK_FILE" ]]; do
			sleep "$REPAINT_SEC"
			[[ -f "$LOCK_FILE" ]] || break
			hcc_screen_paint updates
		done
	) &
	painter_pid=$!
}

run_apt() {
	export DEBIAN_FRONTEND=noninteractive
	apt-get update -qq
	apt-get upgrade -y -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold -qq
}

touch "$LOCK_FILE"
start_painter

{
	printf '\n===== %s =====\n' "$(date -Is)"
	run_apt
	printf '===== finished %s =====\n' "$(date -Is)"
} >>"$LOG_FILE" 2>&1

cleanup
trap - EXIT INT TERM

if [[ -x "$COLLECT_SCRIPT" ]]; then
	"$COLLECT_SCRIPT" >/dev/null 2>&1 || true
fi
