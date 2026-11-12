#!/usr/bin/env bash
# HCC appliance halt / reboot console screen.
#
# Reboot/shutdown: circular unload narrative (services stop like boot starts).
# Maintenance (dashboard restart only): short circular hold.
#
# Owns tty1 for the stop window. Kernel printk is silenced; worker I/O is quiet.
set -uo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
TTY_DEV="${HCC_TTY:-/dev/tty1}"
BANNER_FILE="${HCC_BANNER_WIDE:-$ROOT/hcc-banner.txt}"
DOCKER_WATCH="${HCC_DOCKER_WATCH:-$ROOT/hcc-docker.watch}"
HALT_MSG_PY="${HCC_HALT_MSG_PY:-$ROOT/hcc-halt-preview-gif.py}"
CIRCLE_FB_PY="${HCC_CIRCLE_BOOT_FB:-$ROOT/hcc-boot-circle-fb.py}"
HALT_STEP_TIMEOUT="${HCC_HALT_STEP_TIMEOUT:-5}"
HALT_HOLD_SEC="${HCC_HALT_HOLD_SEC:-8}"
HALT_MAINT_HOLD_SEC="${HCC_MAINT_HOLD_SEC:-4}"
HALT_REPAINT_SEC="${HCC_HALT_REPAINT_SEC:-2}"

# shellcheck source=/dev/null
source "$ROOT/hcc-appliance-screen.lib"

hcc_halt_silence_console() {
	if [[ -w /proc/sys/kernel/printk ]]; then
		echo "1 4 1 7" >/proc/sys/kernel/printk 2>/dev/null || true
	fi
	dmesg -n 1 >/dev/null 2>&1 || true
	setterm -cursor off -blank 0 -powersave off </dev/tty1 >/dev/tty1 2>/dev/null || true
	pkill -f "aplay.*loopsound\.(wav|mp3)" >/dev/null 2>&1 || true
	pkill -f "mpg123.*loopsound\.(wav|mp3)" >/dev/null 2>&1 || true
	[[ -r /run/hcc-loop-sound.pid ]] && {
		pid="$(cat /run/hcc-loop-sound.pid 2>/dev/null || true)"
		[[ -n "$pid" ]] && kill -- "-$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
		rm -f /run/hcc-loop-sound.pid 2>/dev/null || true
	}
}

hcc_halt_mode() {
	local mode=""
	if [[ -r /run/systemd/shutdown/scheduled ]]; then
		mode="$(awk -F= '/^MODE=/{print tolower($2); exit}' /run/systemd/shutdown/scheduled 2>/dev/null || true)"
	fi
	case "$mode" in
		reboot|kexec) echo reboot ;;
		poweroff|halt|power-off) echo shutdown ;;
		*)
			if systemctl list-jobs 2>/dev/null | grep -qE 'reboot\.target|kexec\.target'; then
				echo reboot
			elif systemctl list-jobs 2>/dev/null | grep -qE 'poweroff\.target|halt\.target'; then
				echo shutdown
			else
				echo maintenance
			fi
			;;
	esac
}

hcc_halt_wait_inactive() {
	local unit=$1
	local deadline=$((SECONDS + HALT_STEP_TIMEOUT)) state
	while (( SECONDS < deadline )); do
		state="$(systemctl show -p ActiveState --value "$unit" 2>/dev/null || echo inactive)"
		case "$state" in inactive|dead|failed) return 0 ;; esac
		systemctl stop "$unit" >/dev/null 2>&1 || true
		sleep 0.3
	done
	return 1
}

hcc_halt_wait_container_gone() {
	local name=$1
	local deadline=$((SECONDS + HALT_STEP_TIMEOUT))
	command -v docker >/dev/null 2>&1 || return 0
	while (( SECONDS < deadline )); do
		if ! docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$name"; then
			return 0
		fi
		docker stop -t 8 "$name" >/dev/null 2>&1 || true
		sleep 0.4
	done
	return 1
}

hcc_halt_worker() {
	# ASCII-fallback silent unloader (circle mode does this itself).
	exec >/dev/null 2>&1
	if [[ -r "$DOCKER_WATCH" ]] && command -v docker >/dev/null 2>&1; then
		local name
		while IFS= read -r name || [[ -n "$name" ]]; do
			name="${name%%#*}"
			name="$(echo "$name" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
			[[ -z "$name" ]] && continue
			hcc_halt_wait_container_gone "$name" || true
		done < "$DOCKER_WATCH"
	fi
	hcc_halt_wait_inactive docker.service || true
	local svc
	for svc in smbd nmbd winbind nfs-server; do
		systemctl list-unit-files "${svc}.service" --no-legend 2>/dev/null | grep -q . \
			&& hcc_halt_wait_inactive "${svc}.service" || true
	done
}

hcc_halt_run_circle_unload() {
	local mode=$1
	hcc_circle_fb_available || return 1
	hcc_circle_stop
	# Foreground unload narrative — Stopping / Stopped per service.
	HCC_HALT_STEP_TIMEOUT="$HALT_STEP_TIMEOUT" \
		python3 "$CIRCLE_FB_PY" --mode "$mode"
}

hcc_halt_run() {
	local mode deadline worker hold_sec pid
	mode="$(hcc_halt_mode)"

	if [[ "$mode" == "maintenance" ]]; then
		hold_sec="${HALT_MAINT_HOLD_SEC%.*}"
		if hcc_circle_start "$mode" --hold "$hold_sec"; then
			deadline=$((SECONDS + hold_sec + 1))
			while (( SECONDS < deadline )); do
				[[ -r "$CIRCLE_PID_FILE" ]] || break
				pid="$(cat "$CIRCLE_PID_FILE" 2>/dev/null || true)"
				kill -0 "$pid" 2>/dev/null || break
				sleep 0.2
			done
			hcc_circle_stop
			return 0
		fi
		hcc_halt_paint "$mode"
		deadline=$((SECONDS + hold_sec))
		while (( SECONDS < deadline )); do
			sleep "$HALT_REPAINT_SEC"
			hcc_halt_paint "$mode"
		done
		return 0
	fi

	hcc_halt_silence_console

	# Preferred path: circle unload narrative owns stop + display.
	if hcc_halt_run_circle_unload "$mode"; then
		return 0
	fi

	# ASCII fallback — silent worker + static repaint.
	hold_sec="${HALT_HOLD_SEC%.*}"
	hcc_halt_worker &
	worker=$!
	hcc_halt_paint "$mode"
	deadline=$((SECONDS + hold_sec))
	while (( SECONDS < deadline )); do
		sleep "$HALT_REPAINT_SEC"
		hcc_halt_paint "$mode"
	done
	wait "$worker" 2>/dev/null || true
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
	if [[ -n "${HCC_HALT_FORCE_MODE:-}" ]]; then
		hcc_halt_mode() { echo "$HCC_HALT_FORCE_MODE"; }
	fi
	hcc_halt_run
fi
