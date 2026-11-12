#!/usr/bin/env python3
"""Fullscreen HCC circular status on the dashboard framebuffer (/dev/fb0).

Modes:
  boot         — real readiness waits (replaces "Server is starting")
  reboot       — reverse unload narrative (services stop like boot starts)
  shutdown     — reverse unload narrative
  updates      — spinning status screen
  maintenance  — spinning status screen

Uses real DejaVu Sans lettering (no ASCII box art).

Usage:
  python3 hcc-boot-circle-fb.py
  python3 hcc-boot-circle-fb.py --mode reboot
  python3 hcc-boot-circle-fb.py --mode updates --until-file /run/hcc-updates.lock
  python3 hcc-boot-circle-fb.py --mode maintenance --once
"""
from __future__ import annotations

import argparse
import math
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WATCH = Path("/Backup_Pool/scripts/hcc-docker.watch")
STATUS_FILE = Path(os.environ.get("STATUS_FILE", "/Backup_Pool/scripts/hcc-status.json"))
FONT_SANS = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FB = Path("/dev/fb0")
TTY = Path(os.environ.get("HCC_TTY", "/dev/tty1"))
STEP_TIMEOUT = float(os.environ.get("HCC_BOOT_STEP_TIMEOUT", "90"))
HALT_STEP_TIMEOUT = float(os.environ.get("HCC_HALT_STEP_TIMEOUT", "5"))

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

CORE_SVCS = [
    "ssh", "smbd", "nmbd", "winbind", "docker", "containerd",
    "nfs-server", "cron", "rsyslog", "systemd-timesyncd",
]
HCC_SVCS = [
    "hcc-agent",
    "hcc-docker-ensure",
]

STARTUP_WAV = Path(os.environ.get("HCC_STARTUP_SOUND_FILE", "/Backup_Pool/scripts/startupdash.wav"))
STARTUP_DEV = os.environ.get("HCC_STARTUP_SOUND_DEVICE", "plughw:PCH,0")

STATUS_COPY = {
    "updates": ("Updates in progress", STATUS),
    "reboot": ("Server reboot in progress", WARN),
    "shutdown": ("Server shutdown in progress", WARN),
    "maintenance": ("Maintenance in progress", CHROME),
}

# Actively stopped on reboot/shutdown after Docker (mirrors prior halt worker).
# Leave ssh/cron/rsyslog/timesyncd to systemd.
HALT_CORE_SVCS = ["containerd", "smbd", "nmbd", "winbind", "nfs-server"]


@dataclass
class BootStep:
    kind: str
    label: str
    arg: str = ""


def sh_ok(cmd: list[str], timeout: float = 3.0) -> bool:
    try:
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout)
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
    names = [ln.strip() for ln in sh_out(["zpool", "list", "-H", "-o", "name"]).splitlines() if ln.strip()]
    return names or ["Backup_Pool", "Media_Pool", "Storage_Pool_1", "Storage_Pool_2"]


def watch_containers() -> list[str]:
    if not WATCH.is_file():
        return ["jellyfin", "qbittorrent"]
    out = []
    for ln in WATCH.read_text(encoding="utf-8", errors="replace").splitlines():
        ln = ln.split("#", 1)[0].strip()
        if ln:
            out.append(ln)
    return out


def boot_plan() -> list[BootStep]:
    steps = [
        BootStep("info", "Kernel handoff complete"),
        BootStep("console", "console tty1"),
        BootStep("info", "block devices"),
        BootStep("unit", "ZFS modules", "zfs-load-module.service"),
    ]
    for pool in zpools():
        steps.append(BootStep("pool", f"ZFS pool {pool}", pool))
    steps += [BootStep("network", "network stack"), BootStep("gateway", "gateway")]
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


def halt_plan(mode: str) -> list[BootStep]:
    """Reverse of boot — HCC stack first, then platform services."""
    action = "reboot" if mode == "reboot" else "shutdown"
    final = "Reboot" if mode == "reboot" else "Shutdown"
    steps = [
        BootStep("info", f"Server {action} in progress"),
        BootStep("info", "Unloading HCC services"),
        BootStep("halt_status", "HCC telemetry"),
    ]
    for name in watch_containers():
        steps.append(BootStep("stop_container", name, name))
    for svc in reversed(HCC_SVCS):
        if unit_exists(svc):
            steps.append(BootStep("stop_unit", svc, f"{svc}.service"))
    steps.append(BootStep("stop_docker", "Docker engine"))
    for svc in HALT_CORE_SVCS:
        if unit_exists(svc):
            steps.append(BootStep("stop_unit", svc, f"{svc}.service"))
    steps += [
        BootStep("info", "network stack"),
        BootStep("info", "block devices"),
    ]
    for pool in zpools():
        steps.append(BootStep("info", f"ZFS pool {pool}"))
    steps += [
        BootStep("info", f"Server {action} complete"),
        BootStep("ready", f"HCC {final}"),
    ]
    return steps


def unit_inactive(unit: str) -> bool:
    state = sh_out(["systemctl", "show", "-p", "ActiveState", "--value", unit]).strip()
    return state in {"inactive", "dead", "failed", ""}


def halt_dry_run() -> bool:
    return os.environ.get("HCC_HALT_DRY_RUN", "0") == "1"


def stop_unit(unit: str) -> None:
    if halt_dry_run():
        return
    subprocess.Popen(
        ["systemctl", "stop", unit],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def stop_container(name: str) -> None:
    if halt_dry_run():
        return
    subprocess.Popen(
        ["docker", "stop", "-t", "8", name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def check_halt(step: BootStep) -> str:
    """Return ok | wait | skip | warn for halt steps. Issues stop actions as needed."""
    k, arg = step.kind, step.arg
    if k in {"info", "ready", "halt_status"}:
        return "ok"
    if halt_dry_run():
        # Animate the Stopping line briefly without touching the host.
        return "ok"
    if k == "stop_container":
        names = {ln.strip() for ln in sh_out(["docker", "ps", "--format", "{{.Names}}"]).splitlines()}
        if arg not in names:
            return "ok"
        stop_container(arg)
        return "wait"
    if k == "stop_unit":
        if unit_inactive(arg):
            return "ok"
        stop_unit(arg)
        return "wait"
    if k == "stop_docker":
        if unit_inactive("docker.service"):
            return "ok"
        stop_unit("docker.service")
        return "wait"
    return "skip"


def halt_status_text(step: BootStep) -> str:
    if step.kind == "ready":
        return step.label
    if step.kind == "info":
        if step.label.startswith("Server") or step.label.startswith("Unloading"):
            return step.label
        return f"Stopping {step.label} Service"
    if step.kind == "halt_status":
        return f"Stopping {step.label} Service"
    return f"Stopping {step.label} Service"


def play_startup_sound() -> None:
    if os.environ.get("HCC_STARTUP_SOUND_ENABLED", "1") != "1":
        return
    if not STARTUP_WAV.is_file():
        return
    try:
        subprocess.Popen(
            ["aplay", "-q", "-D", STARTUP_DEV, str(STARTUP_WAV)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        try:
            subprocess.Popen(
                ["aplay", "-q", str(STARTUP_WAV)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            pass


def unit_ready(unit: str) -> bool:
    cond = sh_out(["systemctl", "show", "-p", "ConditionResult", "--value", unit]).strip()
    if cond == "no":
        return True
    state = sh_out(["systemctl", "show", "-p", "ActiveState", "--value", unit]).strip()
    typ = sh_out(["systemctl", "show", "-p", "Type", "--value", unit]).strip()
    result = sh_out(["systemctl", "show", "-p", "Result", "--value", unit]).strip()
    if state == "active":
        return True
    if state in {"activating", "reloading", "failed"}:
        return False
    if typ in {"oneshot", "dbus", "idle"} and result == "success" and state in {"inactive", "dead"}:
        return True
    return result == "exec-condition"


def unit_failed(unit: str) -> bool:
    return sh_out(["systemctl", "show", "-p", "ActiveState", "--value", unit]).strip() == "failed"


def unit_activating(unit: str) -> bool:
    return sh_out(["systemctl", "show", "-p", "ActiveState", "--value", unit]).strip() in {
        "activating", "reloading"
    }


def check_ready(step: BootStep) -> str:
    k, arg = step.kind, step.arg
    if k in {"info", "ready", "console", "sound"}:
        return "ok"
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
        return "ok" if Path("/dev/snd/pcmC0D0p").exists() or Path("/dev/snd/controlC0").exists() else "warn"
    if k == "status":
        return "ok" if STATUS_FILE.is_file() else "warn"
    if k == "pool":
        health = sh_out(["zpool", "list", "-H", "-o", "health", arg]).strip().upper()
        return "ok" if health in {"ONLINE", "DEGRADED"} else "wait"
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
        return "skip"
    return "skip"


def status_text(step: BootStep) -> str:
    if step.kind == "ready":
        return "HCC Ready"
    if step.kind == "sound":
        return "Loading HCC services"
    if step.kind == "info" and (step.label.startswith("Kernel") or step.label.startswith("Server")):
        return step.label
    return f"Starting {step.label} Service"


def font(path: str, size: int):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        try:
            return ImageFont.truetype(FONT_SANS, size)
        except OSError:
            return ImageFont.load_default()


def fb_size() -> tuple[int, int, int]:
    vs = Path("/sys/class/graphics/fb0/virtual_size").read_text().strip()
    w, h = (int(x) for x in vs.split(","))
    bpp = int(Path("/sys/class/graphics/fb0/bits_per_pixel").read_text().strip())
    return w, h, bpp


def text_width(draw: ImageDraw.ImageDraw, text: str, fnt) -> int:
    box = draw.textbbox((0, 0), text, font=fnt)
    return box[2] - box[0]


def fit_text(draw: ImageDraw.ImageDraw, text: str, fnt, max_w: int) -> str:
    shown = text
    while text_width(draw, shown, fnt) > max_w and len(shown) > 12:
        shown = shown[:-2] + "…"
    return shown


def make_frame(
    w: int,
    h: int,
    angle_deg: float,
    text: str,
    color: tuple[int, int, int],
    headline: str | None = None,
    headline_color: tuple[int, int, int] | None = None,
) -> Image.Image:
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)
    logo_f = font(FONT_BOLD, max(72, int(h * 0.085)))
    head_f = font(FONT_SANS, max(28, int(h * 0.034)))
    status_f = font(FONT_SANS, max(24, int(h * 0.028)))

    cx, cy = w / 2, h * 0.42
    r_out = min(w, h) * 0.28
    r_in = r_out * 0.66

    for thick in range(4):
        d.ellipse(
            [cx - r_out - thick, cy - r_out - thick, cx + r_out + thick, cy + r_out + thick],
            outline=RING,
        )
    for i in range(48):
        a = 2 * math.pi * i / 48
        x0 = cx + (r_out - 18) * math.cos(a)
        y0 = cy + (r_out - 18) * math.sin(a)
        x1 = cx + (r_out - 2) * math.cos(a)
        y1 = cy + (r_out - 2) * math.sin(a)
        d.line([(x0, y0), (x1, y1)], fill=TICK, width=2)

    d.ellipse([cx - r_in, cy - r_in, cx + r_in, cy + r_in], outline=(40, 65, 55))
    span = 115
    start = angle_deg - span
    end = angle_deg
    for thick in range(4, 10):
        d.arc([cx - r_in, cy - r_in, cx + r_in, cy + r_in], start=start, end=end, fill=ARC, width=thick)
    for thick in range(6, 14):
        d.arc([cx - r_in, cy - r_in, cx + r_in, cy + r_in], start=end - 22, end=end, fill=ARC_HOT, width=thick)

    # Real font wordmark centered in the ring (no ASCII box).
    logo = "HCC"
    lw = text_width(d, logo, logo_f)
    lh = d.textbbox((0, 0), logo, font=logo_f)[3] - d.textbbox((0, 0), logo, font=logo_f)[1]
    d.text((cx - lw / 2, cy - lh / 2 - 4), logo, font=logo_f, fill=LOGO)

    y = h * 0.76
    if headline:
        shown_h = fit_text(d, headline, head_f, w - 80)
        hw = text_width(d, shown_h, head_f)
        d.text(((w - hw) / 2, y), shown_h, font=head_f, fill=headline_color or WARN)
        y = h * 0.82

    shown = fit_text(d, text, status_f, w - 80)
    sw = text_width(d, shown, status_f)
    d.text(((w - sw) / 2, y), shown, font=status_f, fill=color)
    return img


def blit_fb(img: Image.Image, bpp: int) -> None:
    if bpp != 32:
        raise RuntimeError(f"unsupported bpp {bpp}")
    rgb = img.convert("RGB")
    r, g, b = rgb.split()
    a = Image.new("L", rgb.size, 255)
    bgra = Image.merge("RGBA", (b, g, r, a)).tobytes()
    with FB.open("r+b", buffering=0) as fb:
        fb.write(bgra)


def color_for(step: BootStep, result: str) -> tuple[int, int, int]:
    if step.kind == "ready":
        return READY
    if result == "warn":
        return WARN
    if result == "fail":
        return (220, 90, 90)
    if result == "ok" and step.kind not in {"info", "ready"} and not status_text(step).startswith("Starting"):
        return OK
    if step.kind == "info":
        return CHROME
    return STATUS


def clear_tty() -> None:
    try:
        with TTY.open("w", encoding="utf-8") as tty:
            tty.write("\033[2J\033[H\033[?25l\033[3J")
            tty.flush()
    except OSError:
        pass


def restore_cursor() -> None:
    try:
        with TTY.open("w", encoding="utf-8") as tty:
            tty.write("\033[?25h")
            tty.flush()
    except OSError:
        pass


def run_boot() -> int:
    w, h, bpp = fb_size()
    angle = -90.0
    clear_tty()

    def show(text: str, color: tuple[int, int, int]) -> None:
        nonlocal angle
        blit_fb(make_frame(w, h, angle, text, color), bpp)
        angle = (angle + 10) % 360

    for step in boot_plan():
        label = status_text(step)
        if step.kind == "sound":
            play_startup_sound()
            for _ in range(10):
                show(label, READY)
                time.sleep(0.08)
            continue

        if step.kind in {"info", "ready"}:
            for _ in range(12 if step.kind == "ready" else 6):
                show(label, color_for(step, "ok"))
                time.sleep(0.08)
            continue

        soft = step.kind in {"gateway", "audio", "status", "container"}
        deadline = time.monotonic() + STEP_TIMEOUT
        result = "wait"
        while time.monotonic() < deadline:
            result = check_ready(step)
            show(label, STATUS if result == "wait" else color_for(step, result))
            if result in {"ok", "skip", "fail", "warn"}:
                if result == "fail" and soft:
                    result = "warn"
                break
            time.sleep(0.08)
        else:
            result = "warn"

        ack = {
            "ok": f"Started {step.label}",
            "skip": f"Skipped {step.label}",
            "warn": f"Started {step.label} (warnings)",
            "fail": f"Failed {step.label}",
        }.get(result, label)
        for _ in range(4):
            show(ack, color_for(step, result))
            time.sleep(0.08)

    for _ in range(40):
        show("HCC Ready", READY)
        time.sleep(0.08)

    restore_cursor()
    return 0


def run_halt(mode: str) -> int:
    """Reboot/shutdown unload narrative — headline stays up; Stopping/Stopped below."""
    w, h, bpp = fb_size()
    angle = -90.0
    clear_tty()
    headline = STATUS_COPY[mode][0]
    final = "HCC Reboot" if mode == "reboot" else "HCC Shutdown"

    def show(detail: str, color: tuple[int, int, int]) -> None:
        nonlocal angle
        blit_fb(
            make_frame(
                w, h, angle, detail, color,
                headline=headline,
                headline_color=WARN,
            ),
            bpp,
        )
        angle = (angle + 10) % 360

    for step in halt_plan(mode):
        # Keep the reboot/shutdown headline fixed; only cycle detail lines.
        if step.kind == "info" and step.label.startswith("Server") and "in progress" in step.label:
            for _ in range(6):
                show("Preparing to unload services", STATUS)
                time.sleep(0.08)
            continue
        if step.kind == "ready":
            for _ in range(12):
                show(final, READY)
                time.sleep(0.08)
            continue
        if step.kind == "info" and (
            step.label.startswith("Server") or step.label.startswith("Unloading")
        ):
            for _ in range(5):
                show(step.label, STATUS)
                time.sleep(0.08)
            continue

        label = halt_status_text(step)
        deadline = time.monotonic() + HALT_STEP_TIMEOUT
        result = "wait"
        while time.monotonic() < deadline:
            result = check_halt(step)
            show(label, STATUS if result == "wait" else OK)
            if result in {"ok", "skip", "warn"}:
                break
            time.sleep(0.08)
        else:
            result = "warn"

        ack = {
            "ok": f"Stopped {step.label}",
            "skip": f"Skipped {step.label}",
            "warn": f"Stopped {step.label} (warnings)",
        }.get(result, label)
        for _ in range(4):
            show(ack, WARN if result == "warn" else OK)
            time.sleep(0.08)

    for _ in range(24):
        show(final, READY)
        time.sleep(0.08)
    return 0


def run_status(mode: str, hold: float | None, until_file: Path | None, once: bool) -> int:
    if mode not in STATUS_COPY:
        raise SystemExit(f"unknown status mode: {mode}")
    text, color = STATUS_COPY[mode]
    w, h, bpp = fb_size()
    angle = -90.0
    clear_tty()

    def show() -> None:
        nonlocal angle
        blit_fb(make_frame(w, h, angle, text, color), bpp)
        angle = (angle + 10) % 360

    if once:
        show()
        return 0

    deadline = None if hold is None else time.monotonic() + max(0.0, hold)
    while True:
        if until_file is not None and not until_file.exists():
            break
        if deadline is not None and time.monotonic() >= deadline:
            break
        show()
        time.sleep(0.08)
        # If neither hold nor until-file was given, spin briefly then exit.
        if until_file is None and deadline is None:
            deadline = time.monotonic() + 2.0

    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="HCC circular framebuffer status")
    ap.add_argument(
        "--mode",
        choices=("boot", "updates", "reboot", "shutdown", "maintenance"),
        default="boot",
    )
    ap.add_argument("--hold", type=float, default=None, help="seconds to keep spinning (status modes)")
    ap.add_argument("--until-file", type=Path, default=None, help="spin while this path exists")
    ap.add_argument("--once", action="store_true", help="paint one frame and exit")
    args = ap.parse_args()

    if args.mode == "boot":
        return run_boot()
    # Full unload narrative unless caller asked for a static/hold spinner.
    if args.mode in {"reboot", "shutdown"} and not args.once and args.hold is None and args.until_file is None:
        return run_halt(args.mode)
    return run_status(args.mode, args.hold, args.until_file, args.once)


if __name__ == "__main__":
    raise SystemExit(main())
