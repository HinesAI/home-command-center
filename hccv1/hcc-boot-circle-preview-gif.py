#!/usr/bin/env python3
"""HCC circular boot preview — real readiness waits (not fixed timers).

Each "Starting … Service" line stays on screen until the matching check
passes (same idea as hcc-appliance-boot.lib). On a warm box many steps
finish immediately; on cold boot they linger until the unit/pool/container
is actually up.

Usage:
  # Live terminal preview (recommended)
  python3 /Backup_Pool/scripts/hcc-boot-circle-preview-gif.py --live

  # Record a GIF while waiting for real readiness
  python3 /Backup_Pool/scripts/hcc-boot-circle-preview-gif.py --gif

  python3 /Backup_Pool/scripts/hcc-boot-circle-preview-gif.py --list
"""
from __future__ import annotations

import argparse
import math
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path("/Backup_Pool/scripts")
DEFAULT_OUT = ROOT / "hcc-boot-circle-preview.gif"
HOME_OUT = Path("/home/jhadmin/hcc-boot-circle-preview.gif")
WATCH = ROOT / "hcc-docker.watch"
STATUS_FILE = Path(os.environ.get("STATUS_FILE", "/Backup_Pool/scripts/hcc-status.json"))
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

W, H = 720, 520
SCALE = 2
BG = (8, 12, 18)
RING = (58, 100, 84)
TICK = (48, 82, 70)
ARC = (143, 255, 198)
ARC_HOT = (230, 255, 240)
LOGO = (170, 240, 210)
STATUS = (224, 184, 74)
READY = (143, 255, 198)
OK = (120, 210, 160)
CHROME = (140, 160, 180)
WARN = (230, 180, 60)

STEP_TIMEOUT = float(os.environ.get("HCC_BOOT_STEP_TIMEOUT", "90"))

CORE_SVCS = [
    "ssh",
    "smbd",
    "nmbd",
    "winbind",
    "docker",
    "containerd",
    "nfs-server",
    "cron",
    "rsyslog",
    "systemd-timesyncd",
]

HCC_SVCS = [
    "hcc-agent",
    "hcc-docker-ensure",
]


@dataclass
class BootStep:
    kind: str  # info | unit | pool | network | gateway | docker | container | audio | status | console | ready
    label: str  # shown as "Starting {label} Service" (except info/ready)
    arg: str = ""


def sh_ok(cmd: list[str], timeout: float = 3.0) -> bool:
    try:
        subprocess.check_call(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
        return True
    except Exception:
        return False


def sh_out(cmd: list[str], timeout: float = 5.0) -> str:
    try:
        return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, timeout=timeout)
    except Exception:
        return ""


def unit_exists(name: str) -> bool:
    out = sh_out(["systemctl", "list-unit-files", f"{name}.service", "--no-legend"])
    return any(ln.split() and ln.split()[0].startswith(f"{name}.service") for ln in out.splitlines())


def zpools() -> list[str]:
    out = sh_out(["zpool", "list", "-H", "-o", "name"])
    names = [ln.strip() for ln in out.splitlines() if ln.strip()]
    return names or ["Backup_Pool", "Media_Pool", "Storage_Pool_1", "Storage_Pool_2"]


def watch_containers() -> list[str]:
    if not WATCH.is_file():
        return ["jellyfin", "qbittorrent"]
    names: list[str] = []
    for ln in WATCH.read_text(encoding="utf-8", errors="replace").splitlines():
        ln = ln.split("#", 1)[0].strip()
        if ln:
            names.append(ln)
    return names


def boot_plan() -> list[BootStep]:
    steps: list[BootStep] = [
        BootStep("info", "Kernel handoff complete"),
        BootStep("console", "console tty1"),
        BootStep("info", "block devices"),  # informational quick step
        BootStep("unit", "ZFS modules", "zfs-load-module.service"),
    ]
    for pool in zpools():
        steps.append(BootStep("pool", f"ZFS pool {pool}", pool))
    steps += [
        BootStep("network", "network stack"),
        BootStep("gateway", "gateway"),
    ]
    for svc in CORE_SVCS:
        if unit_exists(svc):
            steps.append(BootStep("unit", svc, f"{svc}.service"))
    steps += [
        BootStep("docker", "Docker engine"),
        BootStep("audio", "audio"),
        BootStep("sound", "HCC startup"),
    ]
    for svc in HCC_SVCS:
        if unit_exists(svc):
            steps.append(BootStep("unit", svc, f"{svc}.service"))
    for name in watch_containers():
        steps.append(BootStep("container", name, name))
    steps += [
        BootStep("status", "HCC telemetry"),
        BootStep("info", "Server startup complete"),
        BootStep("ready", "HCC Ready"),
    ]
    return steps


def unit_ready(unit: str) -> bool:
    cond = sh_out(["systemctl", "show", "-p", "ConditionResult", "--value", unit]).strip()
    if cond == "no":
        return True
    state = sh_out(["systemctl", "show", "-p", "ActiveState", "--value", unit]).strip()
    typ = sh_out(["systemctl", "show", "-p", "Type", "--value", unit]).strip()
    result = sh_out(["systemctl", "show", "-p", "Result", "--value", unit]).strip()
    if state == "active":
        return True
    if state == "failed":
        return False
    if state in {"activating", "reloading"}:
        return False
    if typ in {"oneshot", "dbus", "idle"} and result == "success" and state in {"inactive", "dead"}:
        return True
    if result == "exec-condition":
        return True
    return False


def unit_failed(unit: str) -> bool:
    return sh_out(["systemctl", "show", "-p", "ActiveState", "--value", unit]).strip() == "failed"


def unit_activating(unit: str) -> bool:
    return sh_out(["systemctl", "show", "-p", "ActiveState", "--value", unit]).strip() in {
        "activating",
        "reloading",
    }


def check_ready(step: BootStep) -> str:
    """Return ok | wait | skip | fail | warn."""
    k, arg = step.kind, step.arg
    if k in {"info", "ready", "sound"}:
        return "ok"
    if k == "console":
        return "ok" if (os.access("/dev/tty1", os.W_OK) or True) else "wait"
    if k == "network":
        return "ok" if "default" in sh_out(["ip", "-4", "route", "show", "default"]) else "wait"
    if k == "gateway":
        gw = ""
        for ln in sh_out(["ip", "-4", "route", "show", "default"]).splitlines():
            parts = ln.split()
            if len(parts) >= 3 and parts[0] == "default":
                gw = parts[2]
                break
        if not gw:
            return "warn"
        return "ok" if sh_ok(["ping", "-c1", "-W2", gw], timeout=4) else "wait"
    if k == "docker":
        if not sh_ok(["systemctl", "is-active", "--quiet", "docker"]):
            return "wait"
        return "ok" if sh_ok(["docker", "info"], timeout=8) else "wait"
    if k == "audio":
        if Path("/dev/snd/pcmC0D0p").exists() or Path("/dev/snd/controlC0").exists():
            return "ok"
        return "warn"
    if k == "status":
        return "ok" if STATUS_FILE.is_file() else "warn"
    if k == "pool":
        if not sh_out(["bash", "-lc", "command -v zpool"]):
            return "skip"
        health = sh_out(["zpool", "list", "-H", "-o", "health", arg]).strip().upper()
        if health in {"ONLINE", "DEGRADED"}:
            return "ok"
        return "wait"
    if k == "container":
        names = {ln.strip() for ln in sh_out(["docker", "ps", "--format", "{{.Names}}"]).splitlines()}
        return "ok" if arg in names else "wait"
    if k == "unit":
        if unit_failed(arg):
            return "fail"
        if unit_ready(arg):
            return "ok"
        if unit_activating(arg):
            return "wait"
        # enabled but not running / already finished idle — don't hang
        return "skip"
    return "skip"


def status_text(step: BootStep) -> str:
    if step.kind == "ready":
        return "HCC Ready"
    if step.kind == "sound":
        return "Loading HCC services"
    if step.kind == "info":
        if step.label.startswith("Kernel") or step.label.startswith("Server"):
            return step.label
        return f"Starting {step.label} Service"
    return f"Starting {step.label} Service"


def font(size: int, bold: bool = False):
    path = FONT_BOLD if bold else FONT
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        try:
            return ImageFont.truetype(FONT, size)
        except OSError:
            return ImageFont.load_default()


def make_hires(angle_deg: float) -> Image.Image:
    sw, sh = W * SCALE, H * SCALE
    img = Image.new("RGB", (sw, sh), BG)
    d = ImageDraw.Draw(img)
    cx, cy = sw / 2, 245 * SCALE

    r_out = 148 * SCALE
    bbox_out = [cx - r_out, cy - r_out, cx + r_out, cy + r_out]
    for w in range(3 * SCALE):
        d.ellipse(
            [bbox_out[0] - w, bbox_out[1] - w, bbox_out[2] + w, bbox_out[3] + w],
            outline=RING,
        )
    for i in range(36):
        a = 2 * math.pi * i / 36
        x0 = cx + (134 * SCALE) * math.cos(a)
        y0 = cy + (134 * SCALE) * math.sin(a)
        x1 = cx + (146 * SCALE) * math.cos(a)
        y1 = cy + (146 * SCALE) * math.sin(a)
        d.line([(x0, y0), (x1, y1)], fill=TICK, width=max(1, SCALE))

    r_in = 98 * SCALE
    d.ellipse([cx - r_in, cy - r_in, cx + r_in, cy + r_in], outline=(40, 65, 55))
    span = 115
    start = angle_deg - span
    end = angle_deg
    for w in range(2 * SCALE, 5 * SCALE):
        d.arc([cx - r_in, cy - r_in, cx + r_in, cy + r_in], start=start, end=end, fill=ARC, width=w)
    for w in range(3 * SCALE, 7 * SCALE):
        d.arc(
            [cx - r_in, cy - r_in, cx + r_in, cy + r_in],
            start=end - 22,
            end=end,
            fill=ARC_HOT,
            width=w,
        )
    return img


def status_color(kind: str, result: str = "ok") -> tuple[int, int, int]:
    if kind == "ready" or result == "ok" and kind == "ready":
        return READY
    if result == "warn":
        return WARN
    if result == "fail":
        return (220, 90, 90)
    if kind == "info":
        return CHROME
    return STATUS


def make_frame(angle_deg: float, text: str, color: tuple[int, int, int]) -> Image.Image:
    hi = make_hires(angle_deg)
    img = hi.resize((W, H), Image.Resampling.LANCZOS)
    d = ImageDraw.Draw(img)
    logo_f = font(42, bold=True)
    status_f = font(16)

    logo = "HCC"
    bbox = logo_f.getbbox(logo)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    d.text(((W - tw) / 2, 245 - th / 2 - 2), logo, font=logo_f, fill=LOGO)

    shown = text
    while status_f.getbbox(shown)[2] - status_f.getbbox(shown)[0] > W - 40 and len(shown) > 12:
        shown = shown[:-2] + "…"
    sw = status_f.getbbox(shown)[2] - status_f.getbbox(shown)[0]
    d.text(((W - sw) / 2, 430), shown, font=status_f, fill=color)
    return img


def wait_step(step: BootStep, timeout: float = STEP_TIMEOUT) -> str:
    """Block until ready/skip/fail/warn. Returns result code."""
    if step.kind in {"info", "ready", "sound"}:
        return "ok"
    # Soft steps: don't fail hard
    soft = step.kind in {"gateway", "audio", "status", "container", "console"}
    deadline = time.monotonic() + timeout

    # Unit fast-path: skip idle enabled-but-not-starting units
    if step.kind == "unit":
        r = check_ready(step)
        if r in {"ok", "skip", "fail"}:
            return "warn" if r == "fail" and soft else r

    while time.monotonic() < deadline:
        r = check_ready(step)
        if r == "ok":
            return "ok"
        if r == "fail":
            return "warn" if soft else "fail"
        if r == "skip":
            return "skip"
        if r == "warn":
            return "warn"
        time.sleep(0.35)
    return "warn" if soft else "fail"


def run_live() -> int:
    """ANSI terminal live preview with spinning ring + real waits."""
    steps = boot_plan()
    angle = -90.0
    # hide cursor
    sys.stdout.write("\033[?25l")
    sys.stdout.flush()
    try:
        for step in steps:
            label = status_text(step)
            if step.kind in {"info", "ready", "sound"}:
                _live_paint(angle, label, READY if step.kind == "sound" else status_color(step.kind))
                time.sleep(0.8 if step.kind == "sound" else (0.4 if step.kind == "info" else 1.5))
                angle = (angle + 40) % 360
                continue

            deadline = time.monotonic() + STEP_TIMEOUT
            result = "wait"
            while time.monotonic() < deadline:
                result = check_ready(step)
                color = STATUS if result == "wait" else status_color(step.kind, result)
                _live_paint(angle, label, color)
                if result in {"ok", "skip", "fail", "warn"}:
                    if result == "fail" and step.kind in {"gateway", "audio", "status", "container"}:
                        result = "warn"
                    break
                angle = (angle + 12) % 360
                time.sleep(0.1)
            else:
                result = "warn"
            # brief acknowledge
            ack = {
                "ok": f"Started {step.label}",
                "skip": f"Skipped {step.label}",
                "warn": f"Started {step.label} (warnings)",
                "fail": f"Failed {step.label}",
            }.get(result, label)
            _live_paint(angle, ack, status_color(step.kind, result))
            time.sleep(0.25)
        _live_paint(angle, "HCC Ready", READY)
        time.sleep(1.0)
    finally:
        sys.stdout.write("\033[?25h\n")
        sys.stdout.flush()
    return 0


def _live_paint(angle: float, text: str, color: tuple[int, int, int]) -> None:
    # Compact terminal: draw a simple text spinner + status (full circle GIF is graphical)
    spin = "|/-\\"
    ch = spin[int(angle / 30) % 4]
    r, g, b = color
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.write("              .  ·  ·  .\n")
    sys.stdout.write("          ·               ·\n")
    sys.stdout.write(f"        ·        HCC        ·   {ch}\n")
    sys.stdout.write("          ·               ·\n")
    sys.stdout.write("              ·  ·  ·  .\n\n")
    sys.stdout.write(f"\033[38;2;{r};{g};{b}m  {text}\033[0m\n")
    sys.stdout.flush()


def run_gif(out: Path, frame_ms: int = 100, also_home: bool = True) -> int:
    """Record GIF while performing real readiness waits."""
    steps = boot_plan()
    frames: list[Image.Image] = []
    angle = -90.0
    spin_per_frame = 9.0

    def push(text: str, color: tuple[int, int, int], n: int = 1) -> None:
        nonlocal angle
        for _ in range(max(1, n)):
            frames.append(make_frame(angle, text, color))
            angle = (angle + spin_per_frame) % 360

    for step in steps:
        label = status_text(step)
        if step.kind in {"info", "ready", "sound"}:
            push(
                label,
                READY if step.kind == "sound" else status_color(step.kind),
                n=12 if step.kind == "sound" else (8 if step.kind == "info" else 20),
            )
            continue

        deadline = time.monotonic() + STEP_TIMEOUT
        result = "wait"
        while time.monotonic() < deadline:
            result = check_ready(step)
            color = STATUS if result == "wait" else status_color(step.kind, result)
            frames.append(make_frame(angle, label, color))
            angle = (angle + spin_per_frame) % 360
            if result in {"ok", "skip", "fail", "warn"}:
                if result == "fail" and step.kind in {"gateway", "audio", "status", "container"}:
                    result = "warn"
                break
            # pace roughly with frame_ms while polling ~every few frames
            time.sleep(frame_ms / 1000.0)
        else:
            result = "warn"

        ack = {
            "ok": f"Started {step.label}",
            "skip": f"Skipped {step.label}",
            "warn": f"Started {step.label} (warnings)",
            "fail": f"Failed {step.label}",
        }.get(result, label)
        push(ack, status_color(step.kind, result), n=3)

    if not frames:
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        out,
        save_all=True,
        append_images=frames[1:],
        duration=frame_ms,
        loop=0,
        optimize=False,
    )
    print(f"wrote {out} ({out.stat().st_size} bytes, {len(frames)} frames)")
    if also_home:
        HOME_OUT.write_bytes(out.read_bytes())
        print(f"wrote {HOME_OUT}")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--live", action="store_true", help="Play in terminal with real waits")
    ap.add_argument("--gif", action="store_true", help="Record GIF while waiting for real readiness")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--frame-ms", type=int, default=100)
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    if args.list:
        for s in boot_plan():
            print(f"{s.kind:10}  {status_text(s)}")
        return

    if args.live:
        raise SystemExit(run_live())
    if args.gif or True:
        # default action: gif with real waits
        raise SystemExit(run_gif(args.out, frame_ms=args.frame_ms))


if __name__ == "__main__":
    main()
