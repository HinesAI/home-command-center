#!/usr/bin/env bash
# Terminal preview of the EVERYTHING HCC boot narrative.
# For the animated GIF: python3 /Backup_Pool/scripts/hcc-boot-preview-gif.py
#
# Usage:
#   /Backup_Pool/scripts/hcc-boot-preview.sh
#   HCC_BOOT_PREVIEW_DELAY=0.05 /Backup_Pool/scripts/hcc-boot-preview.sh
set -uo pipefail

export HCC_BOOT_PREVIEW_DELAY="${HCC_BOOT_PREVIEW_DELAY:-0.08}"
export HCC_BOOT_DOT_DELAY="${HCC_BOOT_DOT_DELAY:-0.05}"

# Prefer the Python event list (same source as the GIF) when available.
if command -v python3 >/dev/null 2>&1 && [[ -r /Backup_Pool/scripts/hcc-boot-preview-gif.py ]]; then
	exec python3 - <<'PY'
import os, time, shutil
from importlib.machinery import SourceFileLoader
m = SourceFileLoader("hccgif", "/Backup_Pool/scripts/hcc-boot-preview-gif.py").load_module()

cols = int(os.environ.get("HCC_COLS") or shutil.get_terminal_size((128, 48)).columns)
rows = int(os.environ.get("HCC_ROWS") or shutil.get_terminal_size((128, 48)).lines)
delay = float(os.environ.get("HCC_BOOT_PREVIEW_DELAY", "0.08"))
dot_delay = float(os.environ.get("HCC_BOOT_DOT_DELAY", "0.05"))
static = os.environ.get("HCC_BOOT_PREVIEW_STATIC", "0") == "1"

R="\033[0m"; BOLD="\033[1m"; DIM="\033[2m"; OK="\033[32m"; WARN="\033[33m"
CYN="\033[36m"; ACCENT="\033[38;5;39m"; LOGO="\033[38;5;81m"; MUTED="\033[38;5;245m"; INFO="\033[38;5;250m"
logo = m.load_logo()
events = m.build_script()
completed = []
logo_h = len(logo)
header = 1+1+1+logo_h+1+1+1
footer = 3
viewport = max(8, rows - header - footer)

def redraw(active=None):
    print("\033[H\033[2J\033[3J", end="")
    print(f"{BOLD}{ACCENT}HINES COMMAND CENTER{R}")
    print(f"{MUTED}appliance boot — EVERYTHING / verbose mode{R}\n")
    for ln in logo:
        print(f"{LOGO}{ln}{R}")
    print()
    print(f"{DIM}{'─'*min(72, cols)}{R}\n")
    view = list(completed)
    if active:
        view.append(("active", active))
    if len(view) > viewport:
        view = view[-viewport:]
    for kind, text in view:
        if kind == "warn":
            print(f"  {WARN}! {text}{R}")
        elif kind == "info":
            print(f"  {INFO}- {text}{R}")
        elif kind == "active":
            print(f"  {CYN}> {text}{R}")
        else:
            print(f"  {OK}> {text}{R}")
    for _ in range(viewport - len(view)):
        print()

print("\033[?25l", end="")
try:
    if static:
        for kind, text in events:
            if kind in ("boot", "wait"):
                completed.append(("ok", f"{text}....please wait"))
                if kind == "boot" and text == "System booting":
                    completed.append(("ok", "System boot sequence online"))
                elif kind == "boot":
                    completed.append(("ok", "System ready — transferring to dashboard"))
            elif kind == "warn":
                completed.append(("warn", text))
            elif kind == "info":
                completed.append(("info", text))
            else:
                completed.append(("ok", text))
        redraw()
    else:
        redraw()
        time.sleep(0.2)
        for kind, text in events:
            if kind in ("boot", "wait"):
                for dots in (".", "..", "...", "....please wait"):
                    redraw(f"{text}{dots}")
                    time.sleep(dot_delay)
                completed.append(("ok", f"{text}....please wait"))
                if kind == "boot" and text == "System booting":
                    completed.append(("ok", "System boot sequence online"))
                elif kind == "boot":
                    completed.append(("ok", "System ready — transferring to dashboard"))
                redraw()
                time.sleep(delay)
            else:
                completed.append(("warn" if kind == "warn" else "info" if kind == "info" else "ok", text))
                redraw()
                time.sleep(delay * 0.7)
        time.sleep(0.8)
finally:
    print("\033[?25h")
PY
fi

echo "python3 + hcc-boot-preview-gif.py required for EVERYTHING preview" >&2
exit 1
