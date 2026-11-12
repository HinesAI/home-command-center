#!/usr/bin/env bash
# Start or restart Hines Command Center on the physical monitor.
set -euo pipefail

ROOT="/Backup_Pool/scripts"
PIDFILE="$ROOT/hcc-dashboard.pid"
LOCKFILE="$ROOT/hcc-dashboard.lock"
LOG="$ROOT/hcc-dashboard.log"
SCRIPT="$ROOT/hines-command-center-dashboard.sh"

if command -v systemctl >/dev/null 2>&1 \
	&& systemctl list-unit-files hcc-dashboard.service >/dev/null 2>&1; then
	if [[ "$(id -u)" -eq 0 ]]; then
		systemctl restart hcc-dashboard
	else
		sudo systemctl restart hcc-dashboard
	fi
	echo "Dashboard restarted via systemd (tty1)"
	exit 0
fi

# Fallback when systemd unit is not installed.
if [[ -f "$PIDFILE" ]]; then
	old_pid="$(cat "$PIDFILE" 2>/dev/null || true)"
	if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
		kill "$old_pid" 2>/dev/null || true
		sleep 1
		kill -9 "$old_pid" 2>/dev/null || true
	fi
fi
pkill -f "$SCRIPT" 2>/dev/null || true
sleep 1

exec 9>"$LOCKFILE"
if ! flock -n 9; then
	echo "Dashboard already running (lock held)"
	exit 0
fi

"$ROOT/collect-hcc-status.sh"

export TERM=linux
export LANG=en_US.UTF-8
export LC_CTYPE=en_US.UTF-8
export HCC_COLS=128
export HCC_ROWS=48
setsid bash -c "exec '$SCRIPT'" </dev/null >>"$LOG" 2>&1 &
echo $! >"$PIDFILE"
echo "Dashboard started on tty1 (pid $(cat "$PIDFILE"))"
