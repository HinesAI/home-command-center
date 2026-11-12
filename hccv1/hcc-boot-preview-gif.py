#!/usr/bin/env python3
"""HCC verbose appliance-boot preview + animated GIF.

Logo stays top-left at natural monospace size for the entire boot narrative.
Does not modify GRUB/systemd — preview asset only.

Usage:
  python3 /Backup_Pool/scripts/hcc-boot-preview-gif.py
  python3 /Backup_Pool/scripts/hcc-boot-preview-gif.py --out /tmp/hcc-boot.gif
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path("/Backup_Pool/scripts")
BANNER = ROOT / "hcc-banner.txt"
DEFAULT_OUT = ROOT / "hcc-boot-preview.gif"
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"

# Compact logo (left-locked): render banner then scale down so it stays small
LOGO_FONT_SIZE = 8          # render crisp, then downscale
LOGO_MAX_HEIGHT = 34        # compact strip (~2 status lines tall)
STATUS_FONT_SIZE = 12
LINE_H = 14
PAD_X = 12
PAD_Y = 10
MIN_WIDTH = 720
HEIGHT = 540
BG = (8, 12, 18)
FG_LOGO = (120, 200, 255)
FG_TITLE = (70, 170, 255)
FG_MUTED = (120, 130, 145)
FG_OK = (80, 200, 120)
FG_WARN = (230, 180, 60)
FG_INFO = (190, 195, 205)
FG_ACTIVE = (80, 220, 230)
FG_DIM = (70, 78, 90)

# Current dashboard color-splash startup (plays after verbose boot, with sound)
SPLASH_ITEMS = [
    ("ok", "Starting network manager"),
    ("ok", "Initializing storage pools"),
    ("ok", "Loading Intel and NVIDIA drivers"),
    ("ok", "Mounting Backup_Pool"),
    ("ok", "Starting Docker engine"),
    ("ok", "Starting Nextcloud stack"),
    ("ok", "Starting HCC telemetry collectors"),
    ("warn", "UniFi credentials not configured"),
    ("ok", "Starting HCC dashboard on tty1"),
]
STARTUP_WAV = ROOT / "startupdash.wav"


def load_logo() -> list[str]:
    if BANNER.is_file():
        lines = [ln.rstrip("\n") for ln in BANNER.read_text(encoding="utf-8", errors="replace").splitlines()]
        return [ln for ln in lines if ln.strip()]
    return ["HINES COMMAND CENTER"]


def sh_lines(cmd: list[str]) -> list[str]:
    try:
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, timeout=8)
    except Exception:
        return []
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def enabled_services() -> list[str]:
    lines = sh_lines(["systemctl", "list-unit-files", "--type=service", "--state=enabled", "--no-legend", "--no-pager"])
    names: list[str] = []
    for ln in lines:
        unit = ln.split()[0] if ln.split() else ""
        if unit.endswith(".service"):
            names.append(unit[: -len(".service")])
    # Stable-ish order, drop noisy snap noise last
    primary = [n for n in names if not n.startswith("snapd.")]
    snaps = [n for n in names if n.startswith("snapd.")]
    return primary + snaps


def docker_names() -> list[str]:
    return sh_lines(["docker", "ps", "-a", "--format", "{{.Names}}"])


def zpools() -> list[str]:
    return sh_lines(["zpool", "list", "-H", "-o", "name"])


def build_script() -> list[tuple[str, str]]:
    """Return list of (kind, text). kind: boot|wait|start|info|warn"""
    ev: list[tuple[str, str]] = []
    add = ev.append

    add(("boot", "System booting"))
    add(("info", "Firmware handoff complete"))
    add(("info", "Bootloader stage finished"))
    add(("info", "Kernel image loaded"))
    add(("info", "Initial ramdisk executing"))
    add(("info", "Root device probe complete"))
    add(("info", "Kernel handoff complete"))
    add(("info", "Init system online (systemd)"))
    add(("wait", "Claiming physical console tty1"))
    add(("start", "Console tty1 has been claimed"))
    add(("info", "Cursor hidden on tty1"))
    add(("info", "UTF-8 console mode requested"))

    add(("wait", "Probing local block devices"))
    add(("start", "Service block devices has started"))
    add(("wait", "Starting udev device manager"))
    add(("start", "Service udev has started"))
    add(("wait", "Starting filesystem check services"))
    add(("start", "Service filesystem checks has started"))
    add(("wait", "Mounting root filesystem read-write"))
    add(("start", "Service rootfs remount has started"))
    add(("wait", "Starting encrypted volume targets"))
    add(("start", "Service cryptsetup targets has started"))
    add(("wait", "Starting LVM monitor"))
    add(("start", "Service LVM monitor has started"))

    add(("wait", "Starting ZFS module load"))
    add(("start", "Service ZFS modules has started"))
    for pool in zpools() or ["Backup_Pool", "Media_Pool", "Storage_Pool_1", "Storage_Pool_2"]:
        add(("wait", f"Importing ZFS pool {pool}"))
        add(("start", f"Service ZFS pool {pool} has started"))
        add(("wait", f"Mounting ZFS datasets for {pool}"))
        add(("start", f"Service ZFS mounts for {pool} has started"))
        add(("wait", f"Verifying ZFS health for {pool}"))
        add(("start", f"Service ZFS health check for {pool} has started"))
    add(("info", "Backup_Pool mount point online: /Backup_Pool"))
    add(("info", "HCC scripts path online: /Backup_Pool/scripts"))
    add(("info", "Media library paths online under /Media_Pool"))

    add(("wait", "Starting local-fs target"))
    add(("start", "Service local-fs has started"))
    add(("wait", "Starting sysinit target"))
    add(("start", "Service sysinit has started"))
    add(("wait", "Starting basic target"))
    add(("start", "Service basic target has started"))

    # EVERY enabled systemd service
    for svc in enabled_services():
        add(("wait", f"Starting {svc} service"))
        # Mild warn flavor for known flaky bits in preview
        if svc in {"ModemManager", "open-vm-tools", "vgauth"}:
            add(("warn", f"Service {svc} has started with warnings"))
        else:
            add(("start", f"Service {svc} has started"))

    add(("wait", "Starting network pre-configuration"))
    add(("start", "Service network-pre has started"))
    add(("wait", "Starting network stack"))
    add(("start", "Service network stack has started"))
    add(("wait", "Bringing up primary ethernet interface"))
    add(("start", "Service primary ethernet has started"))
    add(("wait", "Requesting IPv4 addressing"))
    add(("start", "Service IPv4 addressing has started"))
    add(("wait", "Installing default route"))
    add(("start", "Service default route has started"))
    add(("wait", "Reaching gateway (UDM Pro 192.168.4.1)"))
    add(("start", "Service gateway has started"))
    add(("wait", "Resolving Active Directory DNS"))
    add(("start", "Service DNS resolution has started"))
    for dc, ip in (
        ("hinesdc1", "192.168.4.100"),
        ("hinesdc2", "192.168.4.191"),
        ("hinesdc3", "192.168.4.147"),
    ):
        add(("wait", f"Pinging domain controller {dc} ({ip})"))
        add(("start", f"Service {dc} reachability has started"))
    add(("wait", "Checking internet path (1.1.1.1)"))
    add(("start", "Service internet path has started"))
    add(("wait", "Validating LAN host bigbear2 (192.168.4.11)"))
    add(("start", "Service storage host reachability has started"))

    add(("wait", "Waiting for Docker API socket"))
    add(("start", "Service Docker API has started"))
    add(("wait", "Enumerating container runtime"))
    add(("start", "Service container runtime enumeration has started"))

    containers = docker_names() or [
        "jellyfin",
        "qbittorrent",
        "torrent-caddy",
        "ollama",
        "open-webui",
        "ragflow",
        "docker-mysql-1",
        "docker-redis-1",
        "docker-minio-1",
        "docker-infinity-1",
        "ingest-inbox-web",
        "learning-portal",
    ]
    for name in containers:
        add(("wait", f"Starting container {name}"))
        add(("start", f"Service container {name} has started"))

    add(("wait", "Starting NVIDIA device services"))
    add(("start", "Service NVIDIA devices has started"))
    add(("wait", "Binding console GPU path"))
    add(("start", "Service console GPU path has started"))
    add(("wait", "Starting audio subsystem (ALSA)"))
    add(("warn", "Service audio has started with warnings"))
    add(("wait", "Loading HCC startup sound asset"))
    add(("start", "Service startup sound asset has started"))

    add(("wait", "Starting HCC status collectors"))
    add(("start", "Service HCC status collectors has started"))
    add(("wait", "Collecting ZFS telemetry"))
    add(("start", "Service ZFS telemetry has started"))
    add(("wait", "Collecting Docker telemetry"))
    add(("start", "Service Docker telemetry has started"))
    add(("wait", "Collecting network telemetry"))
    add(("start", "Service network telemetry has started"))
    add(("wait", "Writing telemetry snapshot"))
    add(("start", "Service telemetry snapshot has started"))
    add(("wait", "Starting HCC daily report timer"))
    add(("start", "Service HCC daily report timer has started"))
    add(("wait", "Starting HCC agent"))
    add(("start", "Service HCC agent has started"))
    add(("wait", "Starting HCC dashboard runtime"))
    add(("start", "Service HCC dashboard runtime has started"))
    add(("boot", "System ready"))
    return ev


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype(FONT_PATH, size=size)
    except Exception:
        return ImageFont.load_default()


def render_logo_sprite(logo: list[str], logo_fnt: ImageFont.ImageFont) -> Image.Image:
    """Render full ASCII logo, then scale to a compact left-aligned strip."""
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    line_h = LOGO_FONT_SIZE + 1
    max_w = 0
    for ln in logo:
        bbox = probe.textbbox((0, 0), ln, font=logo_fnt)
        max_w = max(max_w, bbox[2] - bbox[0])
    raw = Image.new("RGB", (max(1, max_w + 2), max(1, line_h * len(logo) + 2)), BG)
    d = ImageDraw.Draw(raw)
    y = 0
    for ln in logo:
        d.text((0, y), ln, fill=FG_LOGO, font=logo_fnt)
        y += line_h
    # Downscale to LOGO_MAX_HEIGHT — keeps art readable but not huge
    if raw.height > LOGO_MAX_HEIGHT:
        scale = LOGO_MAX_HEIGHT / raw.height
        new_w = max(1, int(raw.width * scale))
        raw = raw.resize((new_w, LOGO_MAX_HEIGHT), Image.Resampling.NEAREST)
    return raw


def measure_width(logo_sprite: Image.Image) -> int:
    return max(MIN_WIDTH, logo_sprite.width + PAD_X * 2 + 24)


def color_for(kind: str) -> tuple[int, int, int]:
    return {
        "ok": FG_OK,
        "start": FG_OK,
        "boot": FG_OK,
        "warn": FG_WARN,
        "info": FG_INFO,
        "active": FG_ACTIVE,
        "fail": (220, 80, 80),
    }.get(kind, FG_MUTED)


def prefix_for(kind: str) -> str:
    return {
        "warn": "!",
        "info": "-",
        "fail": "x",
        "active": ">",
    }.get(kind, ">")


def render_frame(
    logo_sprite: Image.Image,
    completed: list[tuple[str, str]],
    active: tuple[str, str] | None,
    status_fnt: ImageFont.ImageFont,
    width: int,
) -> Image.Image:
    img = Image.new("RGB", (width, HEIGHT), BG)
    draw = ImageDraw.Draw(img)
    y = PAD_Y
    draw.text((PAD_X, y), "HINES COMMAND CENTER", fill=FG_TITLE, font=status_fnt)
    y += LINE_H
    draw.text((PAD_X, y), "appliance boot — EVERYTHING / verbose mode", fill=FG_MUTED, font=status_fnt)
    y += LINE_H + 4

    # Compact logo strip, left-justified
    img.paste(logo_sprite, (PAD_X, y))
    y += logo_sprite.height + 6
    draw.line((PAD_X, y, width - PAD_X, y), fill=FG_DIM)
    y += 8

    footer_h = 0
    viewport_bottom = HEIGHT - 8
    view: list[tuple[str, str]] = list(completed)
    if active:
        view.append(active)

    max_lines = max(6, (viewport_bottom - y) // LINE_H)
    if len(view) > max_lines:
        view = view[-max_lines:]

    for kind, text in view:
        pref = prefix_for(kind)
        draw.text((PAD_X + 2, y), f"{pref} {text}", fill=color_for(kind), font=status_fnt)
        y += LINE_H

    return img


def band_color(i: int, shift: int = 0) -> tuple[int, int, int]:
    palette = [
        (20, 80, 90),
        (30, 110, 120),
        (40, 140, 150),
        (50, 170, 180),
        (40, 150, 200),
        (30, 120, 180),
        (25, 100, 160),
        (20, 90, 130),
    ]
    return palette[(i + shift) % len(palette)]


def render_splash_frame(
    logo_sprite: Image.Image,
    step: int,
    status_fnt: ImageFont.ImageFont,
    width: int,
) -> Image.Image:
    """Current HCC color-splash startup sequence (pre-dashboard)."""
    img = Image.new("RGB", (width, HEIGHT), BG)
    draw = ImageDraw.Draw(img)
    bw = max(1, width // 64)
    for i in range(0, width, bw):
        draw.rectangle([i, 0, i + bw, 10], fill=band_color(i // bw, step))

    y = 18
    draw.text((PAD_X, y), "Hines Command Center", fill=FG_TITLE, font=status_fnt)
    y += LINE_H
    draw.text((PAD_X, y), "Boot and service initialization", fill=FG_MUTED, font=status_fnt)
    y += LINE_H + 4

    img.paste(logo_sprite, (PAD_X, y))
    y += logo_sprite.height + 10

    steps = len(SPLASH_ITEMS)
    for j, (lvl, text) in enumerate(SPLASH_ITEMS):
        if j < step:
            mark, col = ("[WARN]", FG_WARN) if lvl == "warn" else ("[ OK ]", FG_OK)
        elif j == step:
            mark, col = "[ .. ]", FG_ACTIVE
        else:
            mark, col = "[    ]", FG_DIM
        draw.text((PAD_X + 2, y), f"{mark}  {text}", fill=col, font=status_fnt)
        y += LINE_H

    progress = int((step + 1) * 100 / steps)
    bar_w = 40
    filled = progress * bar_w // 100
    bar = "#" * filled + "-" * (bar_w - filled)
    y += 6
    draw.text((PAD_X, y), f"Progress [{bar}] {progress}%", fill=FG_TITLE, font=status_fnt)

    for i in range(0, width, bw):
        draw.rectangle([i, HEIGHT - 12, i + bw, HEIGHT], fill=band_color(i // bw, step + 3))
    return img


def expand_frames(events: list[tuple[str, str]]) -> list[tuple[list[tuple[str, str]], tuple[str, str] | None, int]]:
    """Each item: (completed_snapshot, active_or_None, duration_ms)."""
    frames: list[tuple[list[tuple[str, str]], tuple[str, str] | None, int]] = []
    completed: list[tuple[str, str]] = []

    for kind, text in events:
        if kind in {"boot", "wait"}:
            base = text
            for dots, dur in ((".", 45), ("..", 45), ("...", 45), ("....please wait", 110)):
                frames.append((list(completed), ("active", f"{base}{dots}"), dur))
            completed.append(("ok", f"{base}....please wait"))
            if kind == "boot" and text == "System booting":
                completed.append(("ok", "System boot sequence online"))
            elif kind == "boot" and text == "System ready":
                completed.append(("ok", "System ready"))
            frames.append((list(completed), None, 55))
        elif kind == "warn":
            completed.append(("warn", text))
            frames.append((list(completed), None, 50))
        elif kind == "info":
            completed.append(("info", text))
            frames.append((list(completed), None, 35))
        else:
            completed.append(("ok", text))
            frames.append((list(completed), None, 45))
    # brief hold before splash handoff
    frames.append((list(completed), None, 400))
    return frames


def to_gif_palette(img: Image.Image) -> Image.Image:
    return img.quantize(colors=128, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--max-frames", type=int, default=0, help="optional cap for quick drafts")
    ap.add_argument("--count-only", action="store_true")
    ap.add_argument("--play-sound", action="store_true", help="play startupdash.wav when splash starts")
    args = ap.parse_args()

    events = build_script()
    if args.count_only:
        print(f"events={len(events)} splash_steps={len(SPLASH_ITEMS)}")
        return 0

    logo = load_logo()
    logo_fnt = font(LOGO_FONT_SIZE)
    status_fnt = font(STATUS_FONT_SIZE)
    logo_sprite = render_logo_sprite(logo, logo_fnt)
    width = measure_width(logo_sprite)
    frame_specs = expand_frames(events)
    if args.max_frames > 0:
        frame_specs = frame_specs[: args.max_frames]

    print(
        f"Building GIF: events={len(events)} boot_frames={len(frame_specs)} "
        f"+ splash logo={logo_sprite.size} canvas={width}x{HEIGHT} -> {args.out}"
    )
    images: list[Image.Image] = []
    durations: list[int] = []
    for i, (completed, active, dur) in enumerate(frame_specs):
        rgb = render_frame(logo_sprite, completed, active, status_fnt, width)
        images.append(to_gif_palette(rgb))
        durations.append(dur)
        if i % 75 == 0:
            print(f"  rendered boot {i}/{len(frame_specs)}")

    # HCC startup splash (matches live dashboard sequence; sound plays on real boot)
    for step in range(len(SPLASH_ITEMS)):
        rgb = render_splash_frame(logo_sprite, step, status_fnt, width)
        images.append(to_gif_palette(rgb))
        durations.append(220)
        print(f"  rendered splash {step + 1}/{len(SPLASH_ITEMS)}")

    # final hold: splash complete → dashboard
    img = Image.new("RGB", (width, HEIGHT), BG)
    draw = ImageDraw.Draw(img)
    bw = max(1, width // 64)
    for i in range(0, width, bw):
        draw.rectangle([i, 0, i + bw, 10], fill=band_color(i // bw, 9))
    y = 18
    draw.text((PAD_X, y), "Hines Command Center", fill=FG_TITLE, font=status_fnt)
    y += LINE_H
    draw.text((PAD_X, y), "Boot and service initialization", fill=FG_MUTED, font=status_fnt)
    y += LINE_H + 4
    img.paste(logo_sprite, (PAD_X, y))
    y += logo_sprite.height + 10
    for lvl, text in SPLASH_ITEMS:
        mark, col = ("[WARN]", FG_WARN) if lvl == "warn" else ("[ OK ]", FG_OK)
        draw.text((PAD_X + 2, y), f"{mark}  {text}", fill=col, font=status_fnt)
        y += LINE_H
    y += 6
    draw.text((PAD_X, y), "Progress [########################################] 100%", fill=FG_TITLE, font=status_fnt)
    y += LINE_H + 4
    draw.text((PAD_X, y), "Hines Command Center dashboard is now online", fill=FG_OK, font=status_fnt)
    for i in range(0, width, bw):
        draw.rectangle([i, HEIGHT - 12, i + bw, HEIGHT], fill=band_color(i // bw, 12))
    images.append(to_gif_palette(img))
    durations.append(2000)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(
        args.out,
        save_all=True,
        append_images=images[1:],
        duration=durations,
        loop=0,
        optimize=False,
        disposal=2,
    )
    size_mb = args.out.stat().st_size / (1024 * 1024)
    print(f"Wrote {args.out} ({size_mb:.1f} MiB, {len(images)} frames)")

    if args.play_sound and STARTUP_WAV.is_file():
        # Best-effort local preview of the real handoff sound
        subprocess.Popen(
            ["sudo", "-n", "aplay", "-q", "-D", "plughw:PCH,0", str(STARTUP_WAV)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
