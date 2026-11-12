#!/usr/bin/env python3
"""Halt preview GIFs + tty ASCII helper.

Startup template (logo top-LEFT + rule), then a single centered line:
  Server Shutdown In Progress
  Server Reboot In Progress
  Maintenance In Progress
  Updates In Progress Please Wait

Uses the largest figlet font that fits the console width on ONE line
at full fidelity (no ASCII downscaling / garbling).

Usage:
  python3 hcc-halt-preview-gif.py --mode both
  python3 hcc-halt-preview-gif.py --print-ascii --mode reboot --cols 128
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path("/Backup_Pool/scripts")
HCC_BANNER = ROOT / "hcc-banner.txt"
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"

WIDTH = 960
HEIGHT = 540
PAD_X = 16
PAD_Y = 14
BG = (8, 12, 18)
FG_LOGO = (120, 200, 255)
FG_TITLE = (70, 170, 255)
FG_DIM = (70, 78, 90)

LOGO_MAX_H = 80

# Largest → smallest. First that fits cols wins.
FIGLET_FONTS = ("big", "standard", "slant", "small", "term")


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype(FONT_PATH, size=size)
    except Exception:
        return ImageFont.load_default()


def figlet(text: str, fig_font: str = "standard", width: int = 400) -> list[str]:
    try:
        out = subprocess.check_output(
            ["figlet", "-f", fig_font, "-w", str(width), text],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return [text]
    lines = [ln.rstrip("\n") for ln in out.splitlines()]
    while lines and not lines[-1].strip():
        lines.pop()
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines:
        return [text]
    w = max(len(ln) for ln in lines)
    return [ln.ljust(w) for ln in lines]


def figlet_banner(text: str, width: int = 400) -> list[str]:
    return figlet(text, "banner", width)


def load_hcc_logo() -> list[str]:
    if HCC_BANNER.is_file():
        lines = [ln.rstrip("\n") for ln in HCC_BANNER.read_text().splitlines() if ln.strip()]
        if lines:
            w = max(len(ln) for ln in lines)
            return [ln.ljust(w) for ln in lines]
    return figlet_banner("HINES") + [""] + figlet_banner("COMMAND CENTER")


def message_phrase(mode: str) -> str:
    if mode == "reboot":
        return "Server Reboot In Progress"
    if mode == "maintenance":
        return "Maintenance In Progress"
    if mode == "updates":
        return "Updates In Progress Please Wait"
    return "Server Shutdown In Progress"


def message_lines_for_cols(mode: str, cols: int) -> list[str]:
    """Exact phrase, one line, largest figlet font that fits — never downscaled."""
    phrase = message_phrase(mode)
    usable = max(20, cols - 2)
    for fig_font in FIGLET_FONTS:
        lines = figlet(phrase, fig_font, width=max(400, usable + 50))
        width = max((len(ln) for ln in lines), default=0)
        if 0 < width <= usable:
            return lines
    return [phrase]


def render_block(lines: list[str], fnt: ImageFont.ImageFont, color: tuple[int, int, int], line_h: int) -> Image.Image:
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    max_w = 1
    for ln in lines:
        bbox = probe.textbbox((0, 0), ln if ln else " ", font=fnt)
        max_w = max(max_w, bbox[2] - bbox[0])
    img = Image.new("RGB", (max_w + 2, max(1, line_h * len(lines))), BG)
    d = ImageDraw.Draw(img)
    y = 0
    for ln in lines:
        d.text((0, y), ln, fill=color, font=fnt)
        y += line_h
    return img


def fit(sprite: Image.Image, max_w: int, max_h: int) -> Image.Image:
    scale = min(max_w / max(1, sprite.width), max_h / max(1, sprite.height))
    if scale >= 0.999:
        return sprite
    return sprite.resize(
        (max(1, int(sprite.width * scale)), max(1, int(sprite.height * scale))),
        Image.Resampling.NEAREST,
    )


def render_frame(mode: str) -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)
    title_fnt = font(14)
    block_fnt = font(10)

    y = PAD_Y
    draw.text((PAD_X, y), "HINES COMMAND CENTER", fill=FG_TITLE, font=title_fnt)
    y += 22

    logo = fit(render_block(load_hcc_logo(), block_fnt, FG_LOGO, 11), WIDTH - PAD_X * 2, LOGO_MAX_H)
    img.paste(logo, (PAD_X, y))
    y += logo.height + 10

    draw.line((PAD_X, y, WIDTH - PAD_X, y), fill=FG_DIM)

    # Preview: render the exact phrase as clean type at ~half logo height
    # (figlet pixel-shrink was unreadable). Live tty still uses figlet ASCII.
    phrase = message_phrase(mode)
    msg_size = max(22, logo.height // 2)
    msg_fnt = font(msg_size)
    probe = ImageDraw.Draw(img)
    bbox = probe.textbbox((0, 0), phrase, font=msg_fnt)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    # Shrink horizontally if needed so it stays one line
    if tw > WIDTH - PAD_X * 2:
        msg_size = max(16, int(msg_size * (WIDTH - PAD_X * 2) / tw))
        msg_fnt = font(msg_size)
        bbox = probe.textbbox((0, 0), phrase, font=msg_fnt)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    mx = (WIDTH - tw) // 2
    my = (HEIGHT - th) // 2
    min_y = y + 16
    if my < min_y:
        my = min_y
    draw.text((mx, my), phrase, fill=FG_LOGO, font=msg_fnt)
    img.info["logo_h"] = logo.height
    img.info["msg_h"] = th
    img.info["msg_w"] = tw
    return img


def to_gif_palette(img: Image.Image) -> Image.Image:
    return img.quantize(colors=48, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)


def build(mode: str, out: Path) -> None:
    raw = render_frame(mode)
    logo_h = int(raw.info.get("logo_h", 0))
    msg_h = int(raw.info.get("msg_h", 0))
    msg_w = int(raw.info.get("msg_w", 0))
    frame = to_gif_palette(raw)
    frames = [frame] * 6
    out.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        out,
        save_all=True,
        append_images=frames[1:],
        duration=[500] * 6,
        loop=0,
        optimize=False,
        disposal=2,
    )
    print(f"Wrote {out} ({out.stat().st_size / 1024:.0f} KiB) logo_h={logo_h} msg_h={msg_h} msg_w={msg_w}")


def print_ascii(mode: str, cols: int, logo_rows: int = 7) -> None:
    del logo_rows
    for ln in message_lines_for_cols(mode, cols):
        print(ln)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("shutdown", "reboot", "maintenance", "updates", "both"), default="both")
    ap.add_argument("--out-dir", type=Path, default=Path("/home/jhadmin"))
    ap.add_argument("--print-ascii", action="store_true")
    ap.add_argument("--cols", type=int, default=128)
    ap.add_argument("--logo-rows", type=int, default=7)
    args = ap.parse_args()

    if args.print_ascii:
        mode = "shutdown" if args.mode == "both" else args.mode
        print_ascii(mode, args.cols, args.logo_rows)
        return 0

    modes = ["shutdown", "reboot"] if args.mode == "both" else [args.mode]
    for mode in modes:
        build(mode, args.out_dir / f"hcc-{mode}-preview.gif")
        build(mode, ROOT / f"hcc-{mode}-preview.gif")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
