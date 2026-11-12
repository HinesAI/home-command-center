#!/usr/bin/env bash
# Install Hines Command Center on the physical monitor (tty1).
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
	echo "Run as root: sudo $0" >&2
	exit 1
fi

ROOT="/Backup_Pool/scripts"
SERVICE="hcc-dashboard.service"

chmod +x "$ROOT/collect-hcc-status.sh" "$ROOT/hines-command-center-dashboard.sh" \
	"$ROOT/send-hcc-daily-report.sh" "$ROOT/start-hcc-dashboard.sh" \
	"$ROOT/hcc-dashboard-preflight.sh" "$ROOT/hcc-nightly-updates.sh" \
	"$ROOT/hcc-docker-ensure.sh"

if ! command -v figlet >/dev/null 2>&1; then
	apt-get install -y figlet 2>/dev/null || true
fi
# Side-by-side banner: Hines (left) + Command Center (right), fixed columns — do not per-line trim
python3 << 'PY' > "$ROOT/hcc-banner.txt"
import subprocess

def figlet(text):
    r = subprocess.run(
        ['docker', 'run', '--rm', 'alpine', 'sh', '-c',
         f'apk add figlet >/dev/null 2>&1 && figlet -f banner "{text}"'],
        capture_output=True, text=True, check=True)
    lines = [l.rstrip('\n') for l in r.stdout.splitlines()]
    while lines and not lines[-1].strip():
        lines.pop()
    return lines[:7]

hines, command, center = figlet('Hines'), figlet('Command'), figlet('Center')
LW = max(len(l.rstrip()) for l in hines)
CW = max(len(l.rstrip()) for l in command)
right = [f'{command[i].rstrip():<{CW}}   {center[i].rstrip()}' for i in range(7)]
for i in range(7):
    print(f'{hines[i].rstrip():<{LW}}   {right[i]}')
PY

"$ROOT/collect-hcc-status.sh"

cp "$ROOT/systemd/$SERVICE" "/etc/systemd/system/$SERVICE"
cp "$ROOT/systemd/hcc-status-collect.service" /etc/systemd/system/
cp "$ROOT/systemd/hcc-status-collect.timer" /etc/systemd/system/
cp "$ROOT/systemd/hcc-daily-report.service" /etc/systemd/system/
cp "$ROOT/systemd/hcc-daily-report.timer" /etc/systemd/system/
cp "$ROOT/systemd/hcc-nightly-updates.service" /etc/systemd/system/
cp "$ROOT/systemd/hcc-nightly-updates.timer" /etc/systemd/system/
cp "$ROOT/systemd/hcc-docker-ensure.service" /etc/systemd/system/ 2>/dev/null || true

systemctl daemon-reload
systemctl disable --now getty@tty1.service 2>/dev/null || true
systemctl enable --now "$SERVICE"
systemctl enable --now hcc-status-collect.timer 2>/dev/null || true
systemctl enable --now hcc-nightly-updates.timer 2>/dev/null || true
systemctl enable --now hcc-docker-ensure.service 2>/dev/null || true
# HCC owns the nightly update window; disable Ubuntu's random apt timers.
systemctl disable --now apt-daily.timer apt-daily-upgrade.timer 2>/dev/null || true
if [[ -f "$ROOT/hcc-email.env" ]]; then
	systemctl enable --now hcc-daily-report.timer 2>/dev/null || true
fi

echo
echo "Hines Command Center is now on tty1 (physical monitor)."
echo "  Switch to it: Ctrl+Alt+F1"
echo "  Get a shell:  Ctrl+Alt+F2 (or another F-key)"
echo "  Service:      systemctl status hcc-dashboard"
if [[ ! -f "$ROOT/hcc-email.env" ]]; then
	echo
	echo "Daily email reports are available."
	echo "  1) cp $ROOT/hcc-email.env.example $ROOT/hcc-email.env"
	echo "  2) edit SMTP/to/from settings"
	echo "  3) chmod 600 $ROOT/hcc-email.env"
	echo "  4) sudo systemctl enable --now hcc-daily-report.timer"
fi
