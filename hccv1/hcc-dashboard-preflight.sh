#!/usr/bin/env bash
# Clear stale HCC lock/pid after unclean shutdown (power loss, kill -9).
set -euo pipefail

ROOT="/Backup_Pool/scripts"
LOCK="$ROOT/hcc-dashboard.lock"
PID="$ROOT/hcc-dashboard.pid"
SCRIPT="$ROOT/hines-command-center-dashboard.sh"

dashboard_running() {
	pgrep -f "$SCRIPT" >/dev/null 2>&1
}

if dashboard_running; then
	exit 0
fi

if [[ -f "$PID" ]]; then
	stale_pid="$(cat "$PID" 2>/dev/null || true)"
	if [[ -z "$stale_pid" ]] || ! kill -0 "$stale_pid" 2>/dev/null; then
		rm -f "$LOCK" "$PID"
	fi
else
	rm -f "$LOCK"
fi

exit 0
