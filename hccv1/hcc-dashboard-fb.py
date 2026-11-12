#!/usr/bin/env python3
"""Framebuffer HCC live dashboard — same visual language as the circle boot screens.

Dark navy field, mint accents, DejaVu Sans lettering. Reads hcc-status.json
(or JSON on stdin) and blits a full frame to /dev/fb0.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from http.cookiejar import CookieJar
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

STATUS_FILE = Path(os.environ.get("STATUS_FILE", "/Backup_Pool/scripts/hcc-status.json"))
WATCH = Path("/Backup_Pool/scripts/hcc-docker.watch")
FRIGATE_ENV = Path(os.environ.get("HCC_FRIGATE_ENV", "/Backup_Pool/scripts/hcc-frigate.env"))
SNAP_CACHE = Path(os.environ.get("HCC_FRIGATE_SNAP_DIR", "/run/hcc-frigate-snaps"))
SNAP_TTL = float(os.environ.get("HCC_FRIGATE_SNAP_TTL", "45"))
SNAP_FETCH_H = int(os.environ.get("HCC_FRIGATE_SNAP_H", "160"))
PREVIEWS_ENABLED = os.environ.get("HCC_DASHBOARD_FRIGATE_PREVIEWS", "1") == "1"
FONT_SANS = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FB = Path("/dev/fb0")
TTY = Path(os.environ.get("HCC_TTY", "/dev/tty1"))

BG = (8, 12, 18)
PANEL = (16, 24, 34)
PANEL_HI = (22, 32, 44)
RING = (58, 100, 84)
ARC = (143, 255, 198)
LOGO = (170, 240, 210)
STATUS = (224, 184, 74)
READY = (143, 255, 198)
OK = (120, 210, 160)
CHROME = (140, 160, 180)
MUTED = (110, 128, 145)
WARN = (230, 180, 60)
BAD = (220, 90, 90)
WHITE = (230, 236, 240)
RULE = (48, 72, 86)
CARD_PAD = 12
SUN = (240, 196, 72)
CLOUD = (168, 188, 205)
RAIN = (110, 170, 220)
SNOW = (210, 225, 240)
FOG = (150, 160, 170)
STORM = (190, 170, 255)
NIGHT = (160, 180, 230)
LOCAL_TZ = ZoneInfo(os.environ.get("TZ", "America/Chicago"))


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


def blit_fb(img: Image.Image, bpp: int) -> None:
    if bpp != 32:
        raise RuntimeError(f"unsupported bpp {bpp}")
    rgb = img.convert("RGB")
    r, g, b = rgb.split()
    a = Image.new("L", rgb.size, 255)
    bgra = Image.merge("RGBA", (b, g, r, a)).tobytes()
    with FB.open("r+b", buffering=0) as fb:
        fb.write(bgra)


def clear_tty() -> None:
    try:
        with TTY.open("w", encoding="utf-8") as tty:
            tty.write("\033[2J\033[H\033[?25l\033[3J")
            tty.flush()
    except OSError:
        pass


def tw(d: ImageDraw.ImageDraw, text: str, fnt) -> int:
    box = d.textbbox((0, 0), text, font=fnt)
    return box[2] - box[0]


def th(d: ImageDraw.ImageDraw, text: str, fnt) -> int:
    box = d.textbbox((0, 0), text, font=fnt)
    return box[3] - box[1]


def fit(d: ImageDraw.ImageDraw, text: str, fnt, max_w: int) -> str:
    s = text
    while tw(d, s, fnt) > max_w and len(s) > 4:
        s = s[:-2] + "…"
    return s


def state_color(state: str) -> tuple[int, int, int]:
    s = (state or "").lower()
    if s in {"active", "online", "running", "healthy", "up", "ok", "closed"}:
        return OK
    if s in {"activating", "starting", "degraded", "open"}:
        return WARN
    if s in {"failed", "offline", "stopped", "down", "bad"}:
        return BAD
    if s in {"ONLINE"} or s == "online":
        return OK
    if s.upper() in {"ONLINE", "DEGRADED"}:
        return OK if s.upper() == "ONLINE" else WARN
    return CHROME


def health_color(health: str) -> tuple[int, int, int]:
    h = (health or "").upper()
    if h == "ONLINE":
        return OK
    if h == "DEGRADED":
        return WARN
    return BAD


def pct_color(pct: float) -> tuple[int, int, int]:
    if pct >= 90:
        return BAD
    if pct >= 75:
        return WARN
    return OK


def watch_names() -> list[str]:
    if not WATCH.is_file():
        return ["jellyfin", "qbittorrent"]
    out = []
    for ln in WATCH.read_text(encoding="utf-8", errors="replace").splitlines():
        ln = ln.split("#", 1)[0].strip()
        if ln:
            out.append(ln)
    return out


def draw_bar(d: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, pct: float) -> None:
    pct = max(0.0, min(100.0, float(pct)))
    d.rounded_rectangle([x, y, x + w, y + h], radius=3, outline=RULE, fill=(18, 26, 34))
    fill_w = int(w * pct / 100.0)
    if fill_w > 0:
        d.rounded_rectangle([x, y, x + fill_w, y + h], radius=3, fill=pct_color(pct))


def section_title(d: ImageDraw.ImageDraw, x: int, y: int, title: str, fnt) -> int:
    d.text((x, y), title.upper(), font=fnt, fill=ARC)
    return y + th(d, title, fnt) + 10


CARD_HEADER = 32
CARD_BOTTOM_PAD = 10


def draw_card(d: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, title: str, f_sec) -> tuple[int, int, int]:
    """Draw a soft card shell. Returns (content_x, content_y, content_width)."""
    d.rounded_rectangle([x + 2, y + 2, x + w + 2, y + h + 2], radius=10, fill=(4, 6, 10))
    d.rounded_rectangle([x, y, x + w, y + h], radius=10, fill=PANEL, outline=RULE, width=1)
    d.rounded_rectangle([x + 1, y + 1, x + w - 1, y + 4], radius=3, fill=RING)
    d.text((x + CARD_PAD, y + 10), title.upper(), font=f_sec, fill=ARC)
    return x + CARD_PAD, y + CARD_HEADER, w - 2 * CARD_PAD


def paint_proxmox_body(d, cx: int, cy: int, cw: int, data: dict, f_tiny) -> int:
    """Paint Proxmox content; returns y just below the last line."""
    for node in (data.get("proxmox") or []):
        name = str(node.get("name") or "?")
        online = bool(node.get("online"))
        if online:
            lat = node.get("latency_ms")
            lat_s = f"{float(lat):.2f}ms" if lat is not None else "?"
            ui = "UI ok" if node.get("ui_ok") else "UI down"
            cy = text_row(d, cx, cy, f"{name}  v{node.get('version') or '?'}  {node.get('ip') or ''}", f_tiny, WHITE, cw)
            cpu = float(node.get("cpu_pct") or 0)
            memp = float(node.get("mem_pct") or 0)
            cy = text_row(
                d, cx, cy,
                f"CPU {cpu:.0f}%  MEM {memp:.0f}%  "
                f"VMs {node.get('vms_running')}/{node.get('vms_total')}  {lat_s}  {ui}",
                f_tiny, CHROME, cw,
            )
            draw_bar(d, cx, cy, max(40, int(cw * 0.45)), 5, cpu)
            draw_bar(d, cx + int(cw * 0.50), cy, max(40, int(cw * 0.45)), 5, memp)
            cy += 9
        else:
            cy = text_row(d, cx, cy, f"{name}  OFFLINE  {node.get('ip') or ''}", f_tiny, BAD, cw)

    workloads = data.get("workloads") or []
    running = [vm for vm in workloads if (vm.get("status") or "") == "running"]
    stopped = [vm for vm in workloads if (vm.get("status") or "") != "running"]
    if running:
        cy = text_row(d, cx, cy, "VM fleet", f_tiny, MUTED, cw)
        col_gap = 10
        col_w = max(40, (cw - col_gap) // 2)
        y_l, y_r = cy, cy
        for i, vm in enumerate(running):
            os_tag = "L" if (vm.get("os") or "").lower().startswith("lin") else (
                "W" if (vm.get("os") or "").lower().startswith("win") else "?"
            )
            line = (
                f"{os_tag} {vm.get('name')}  "
                f"{vm.get('cpu_pct')}%/{vm.get('mem_pct')}%/{vm.get('mem_gb')}G  "
                f"{vm.get('node')}"
            )
            if i % 2 == 0:
                y_l = text_row(d, cx, y_l, line, f_tiny, CHROME, col_w)
            else:
                y_r = text_row(d, cx + col_w + col_gap, y_r, line, f_tiny, CHROME, col_w)
        cy = max(y_l, y_r)
    if stopped:
        cy = text_row(
            d, cx, cy,
            f"{len(stopped)} stopped: " + ", ".join(str(vm.get("name")) for vm in stopped[:8]),
            f_tiny, WARN, cw,
        )
    return cy


def paint_frigate_home_body(d, cx: int, cy0: int, cw: int, data: dict, f_tiny, f_small) -> int:
    """Paint split Frigate | Home content; returns y just below the taller column."""
    sub_gap = 14
    left_w = int(cw * 0.55)
    right_x = cx + left_w + sub_gap
    right_w = cw - left_w - sub_gap

    # Frigate column
    fx, cy = cx, cy0
    fr = data.get("frigate") or {}
    if fr.get("ok"):
        up_h = int((fr.get("uptime_sec") or 0) / 3600)
        gpu = fr.get("gpu") or {}
        cy = text_row(d, fx, cy, "Frigate", f_tiny, MUTED, left_w)
        cy = text_row(
            d, fx, cy,
            f"v{fr.get('version', '?')}  {fr.get('latency_ms', '?')}ms  up {up_h}h",
            f_tiny, CHROME, left_w,
        )
        cy = text_row(
            d, fx, cy,
            f"store {fr.get('storage_used_gb')}G used / {fr.get('storage_free_gb')}G free  ({fr.get('storage_pct')}%)",
            f_tiny, MUTED, left_w,
        )
        if fr.get("storage_pct") is not None:
            draw_bar(d, fx, cy, left_w, 6, float(fr.get("storage_pct") or 0))
            cy += 10
        cy = text_row(
            d, fx, cy,
            f"{gpu.get('name', 'GPU')}  {gpu.get('gpu', '?')}  mem {gpu.get('mem', '?')}  "
            f"dec {gpu.get('dec', '?')}  inf {fr.get('inference_ms')}ms",
            f_tiny, CHROME, left_w,
        )
        cy = text_row(d, fx, cy, "Cameras", f_tiny, MUTED, left_w)
        for cam in (fr.get("cameras") or []):
            short = cam.get("short") or cam.get("name") or "?"
            fps = float(cam.get("camera_fps") or 0)
            det = float(cam.get("detection_fps") or 0)
            skipped = float(cam.get("skipped_fps") or 0)
            en = "on" if cam.get("enabled") else "off"
            cy = kv_right(
                d, fx, cy, left_w,
                f"{short}  {fps:.0f}fps det {det:.1f}",
                f"skip {skipped:.1f} {en}",
                f_tiny, f_tiny,
                WHITE if cam.get("enabled") else MUTED,
                OK if cam.get("enabled") else MUTED,
            )
        recent = fr.get("recent") or []
        if recent:
            bits = [f"{ev.get('label')}@{ev.get('camera')}" for ev in recent[:4]]
            cy = text_row(d, fx, cy, "Recent  " + " · ".join(bits), f_tiny, STATUS, left_w)
    else:
        cy = text_row(d, fx, cy, "Frigate unreachable", f_small, BAD, left_w)
    left_end = cy

    # Home Assistant column
    hx, cy = right_x, cy0
    ha = data.get("homeassistant") or {}
    if ha.get("ok"):
        hav = ha.get("version") or ""
        cy = text_row(d, hx, cy, f"Home Assistant{(' v' + str(hav)) if hav else ''}", f_tiny, MUTED, right_w)
        for thm in list(ha.get("thermostats") or []):
            name = str(thm.get("name") or "Thermostat")
            cur = thm.get("current_temp")
            tgt = thm.get("target_temp")
            unit = thm.get("unit") or "°"
            action = thm.get("hvac_action") or thm.get("state") or "?"
            if cur is None and tgt is None:
                cy = kv_right(d, hx, cy, right_w, name, str(action), f_tiny, f_tiny, WHITE, WARN)
            else:
                cy = text_row(d, hx, cy, name, f_tiny, WHITE, right_w)
                cy = text_row(d, hx, cy, f"{cur}{unit} → {tgt}{unit}  {action}", f_tiny, CHROME, right_w)
        doors = list(ha.get("doors") or [])
        open_n = sum(1 for door in doors if str(door.get("state") or "").lower() == "open")
        cy = text_row(
            d, hx, cy,
            f"Doors  {open_n} open / {max(0, len(doors) - open_n)} closed",
            f_tiny, WARN if open_n else OK, right_w,
        )
        for door in doors:
            st = str(door.get("state") or "?")
            cy = kv_right(
                d, hx, cy, right_w,
                str(door.get("name") or "?"),
                st.upper(),
                f_tiny, f_tiny, WHITE, state_color(st),
            )
    elif ha.get("configured"):
        cy = text_row(d, hx, cy, "HA API failed", f_tiny, BAD, right_w)
    else:
        cy = text_row(d, hx, cy, "HA not configured", f_tiny, MUTED, right_w)
    right_end = cy

    # Divider only for the content span
    end = max(left_end, right_end)
    d.line([(right_x - sub_gap // 2, cy0), (right_x - sub_gap // 2, end)], fill=RULE, width=1)
    return end


def text_row(d, x, y, text, fnt, color, max_w) -> int:
    t = fit(d, text, fnt, max_w)
    d.text((x, y), t, font=fnt, fill=color)
    return y + th(d, t, fnt) + 3


def kv_right(d, x, y, width, left, right, f_left, f_right, c_left, c_right) -> int:
    d.text((x, y), fit(d, left, f_left, width - 80), font=f_left, fill=c_left)
    rw = tw(d, right, f_right)
    d.text((x + width - rw, y + 1), right, font=f_right, fill=c_right)
    return y + th(d, left, f_left) + 4


def load_data(path: Path | None, use_stdin: bool) -> dict:
    if use_stdin and not sys.stdin.isatty():
        return json.load(sys.stdin)
    src = path or STATUS_FILE
    return json.loads(src.read_text(encoding="utf-8"))


def _load_dotenv(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for ln in path.read_text(encoding="utf-8", errors="replace").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#") or "=" not in ln:
            continue
        k, v = ln.split("=", 1)
        out[k.strip()] = v.strip().strip("'").strip('"')
    return out


def frigate_opener(base_url: str):
    """Authenticated opener for Frigate (token or login cookie)."""
    env = _load_dotenv(FRIGATE_ENV)
    token = os.environ.get("HCC_FRIGATE_TOKEN") or env.get("HCC_FRIGATE_TOKEN", "")
    user = os.environ.get("HCC_FRIGATE_USER") or env.get("HCC_FRIGATE_USER", "")
    password = os.environ.get("HCC_FRIGATE_PASSWORD") or env.get("HCC_FRIGATE_PASSWORD", "")
    ctx = ssl._create_unverified_context()
    cj = CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ctx),
        urllib.request.HTTPCookieProcessor(cj),
    )
    if token:
        opener.addheaders = [("Authorization", f"Bearer {token}")]
        return opener
    if user and password:
        body = json.dumps({"user": user, "password": password}).encode()
        req = urllib.request.Request(
            f"{base_url.rstrip('/')}/api/login",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            opener.open(req, timeout=5).read()
        except Exception:
            pass
    return opener


def fetch_camera_snapshot(opener, base_url: str, camera: str) -> Image.Image | None:
    """Fetch/cached Frigate latest.jpg for one camera."""
    try:
        SNAP_CACHE.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    cache = SNAP_CACHE / f"{camera}.jpg"
    now = time.time()
    if cache.is_file() and now - cache.stat().st_mtime < SNAP_TTL:
        try:
            return Image.open(cache).convert("RGB")
        except Exception:
            pass
    url = f"{base_url.rstrip('/')}/api/{camera}/latest.jpg?h={SNAP_FETCH_H}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "hcc-dashboard"})
        with opener.open(req, timeout=4) as resp:
            data = resp.read()
        cache.write_bytes(data)
        from io import BytesIO

        return Image.open(BytesIO(data)).convert("RGB")
    except Exception:
        if cache.is_file():
            try:
                return Image.open(cache).convert("RGB")
            except Exception:
                return None
        return None


def load_camera_previews(data: dict) -> list[tuple[str, str, Image.Image | None]]:
    """Return [(name, short, image|None), ...] for Frigate cameras."""
    fr = data.get("frigate") or {}
    cams = list(fr.get("cameras") or [])
    if not PREVIEWS_ENABLED or not fr.get("ok") or not cams:
        return [(str(c.get("name") or "?"), str(c.get("short") or c.get("name") or "?"), None) for c in cams]
    base = str(fr.get("url") or os.environ.get("HCC_FRIGATE_URL") or "https://192.168.4.101:8971")
    try:
        opener = frigate_opener(base)
    except Exception:
        return [(str(c.get("name") or "?"), str(c.get("short") or c.get("name") or "?"), None) for c in cams]
    out: list[tuple[str, str, Image.Image | None]] = []
    for cam in cams:
        name = str(cam.get("name") or "?")
        short = str(cam.get("short") or name)
        out.append((name, short, fetch_camera_snapshot(opener, base, name)))
    return out


# Keep camera strip compact even when vertical space is plentiful after a short card row.
PREVIEW_MAX_THUMB_H = 120


def _camera_thumb_geometry(width: int, camera_count: int, max_h: int | None = None) -> tuple[int, int, int, int, int, int]:
    """Return (thumb_w, thumb_h, card_h, per_row, rows, gap). Shrinks thumbs if max_h is set."""
    if camera_count <= 0:
        return 0, 0, 0, 0, 0, 8
    gap = 8
    per_row = min(8, camera_count)
    rows = (camera_count + per_row - 1) // per_row
    usable = max(80, width - 2 * CARD_PAD)
    # Prefer width-fit, then cap height so previews stay strip-sized.
    thumb_w = max(64, (usable - gap * (per_row - 1)) // per_row)
    thumb_h = int(thumb_w * 9 / 16)
    if thumb_h > PREVIEW_MAX_THUMB_H:
        thumb_h = PREVIEW_MAX_THUMB_H
        thumb_w = int(thumb_h * 16 / 9)
    card_h = CARD_HEADER + rows * (thumb_h + gap) - gap + CARD_BOTTOM_PAD
    if max_h is not None and max_h > 0 and card_h > max_h and rows > 0:
        content = max(40, max_h - CARD_HEADER - CARD_BOTTOM_PAD)
        thumb_h = max(36, min(PREVIEW_MAX_THUMB_H, (content - gap * (rows - 1)) // rows))
        thumb_w = max(48, int(thumb_h * 16 / 9))
        # Cap width so a row still fits; leave unused space on the right.
        max_tw = max(48, (usable - gap * (per_row - 1)) // per_row)
        if thumb_w > max_tw:
            thumb_w = max_tw
            thumb_h = int(thumb_w * 9 / 16)
        card_h = CARD_HEADER + rows * (thumb_h + gap) - gap + CARD_BOTTOM_PAD
        card_h = min(card_h, max_h)
    return thumb_w, thumb_h, card_h, per_row, rows, gap


def camera_preview_strip_height(
    width: int, camera_count: int, f_tiny, max_h: int | None = None
) -> int:
    """Estimate strip height for layout budgeting (max 8 thumbs per row)."""
    if camera_count <= 0:
        return 0
    return _camera_thumb_geometry(width, camera_count, max_h)[2]


def paint_camera_preview_strip(
    img: Image.Image,
    d: ImageDraw.ImageDraw,
    x: int,
    y: int,
    width: int,
    previews: list[tuple[str, str, Image.Image | None]],
    f_tiny,
    f_sec=None,
    max_h: int | None = None,
) -> int:
    """Camera previews under Proxmox — L→R, max 8/row, name in lower-left of each thumb."""
    if not previews:
        return y
    n = len(previews)
    thumb_w, thumb_h, card_h, per_row, _rows, gap = _camera_thumb_geometry(width, n, max_h)
    if thumb_w <= 0 or thumb_h <= 0:
        return y

    title_font = f_sec or font(FONT_BOLD, 13)
    draw_card(d, x, y, width, card_h, "Camera Previews", title_font)
    content_y = y + CARD_HEADER

    for i, (_name, short, snap) in enumerate(previews):
        row = i // per_row
        col = i % per_row
        tx = x + CARD_PAD + col * (thumb_w + gap)
        ty = content_y + row * (thumb_h + gap)

        d.rounded_rectangle([tx, ty, tx + thumb_w, ty + thumb_h], radius=6, outline=RULE, fill=(10, 14, 20))
        if snap is not None:
            fitted = snap.copy()
            fitted.thumbnail((thumb_w - 2, thumb_h - 2), Image.Resampling.LANCZOS)
            px = tx + (thumb_w - fitted.width) // 2
            py = ty + (thumb_h - fitted.height) // 2
            img.paste(fitted, (px, py))
        else:
            msg = "no preview"
            mw = tw(d, msg, f_tiny)
            d.text((tx + (thumb_w - mw) / 2, ty + thumb_h / 2 - 6), msg, font=f_tiny, fill=MUTED)

        # Name badge — lower left of the preview
        label = fit(d, short, f_tiny, thumb_w - 16)
        lw = tw(d, label, f_tiny)
        lh = th(d, label, f_tiny)
        bx0 = tx + 6
        by0 = ty + thumb_h - lh - 10
        bx1 = bx0 + lw + 10
        by1 = by0 + lh + 6
        d.rectangle([bx0, by0, bx1, by1], fill=(8, 12, 18))
        d.text((bx0 + 5, by0 + 2), label, font=f_tiny, fill=WHITE)

    return y + card_h


def _cloud(d: ImageDraw.ImageDraw, cx: float, cy: float, scale: float, fill=CLOUD) -> None:
    scale = max(0.55, float(scale))
    d.ellipse([cx - 16 * scale, cy - 4 * scale, cx - 2 * scale, cy + 10 * scale], fill=fill)
    d.ellipse([cx - 6 * scale, cy - 12 * scale, cx + 12 * scale, cy + 6 * scale], fill=fill)
    d.ellipse([cx + 2 * scale, cy - 2 * scale, cx + 18 * scale, cy + 12 * scale], fill=fill)
    x0, y0 = cx - 14 * scale, cy + 2 * scale
    x1, y1 = cx + 16 * scale, cy + 12 * scale
    if y1 > y0 and x1 > x0:
        d.ellipse([x0, y0, x1, y1], fill=fill)


def draw_weather_icon(d: ImageDraw.ImageDraw, cx: float, cy: float, condition: str, size: int = 36) -> None:
    """Simple geometric weather glyph (no emoji / no external assets)."""
    cond = (condition or "").lower().replace("-", "").replace("_", "").replace(" ", "")
    scale = size / 36.0

    if cond in {"sunny", "clear", "exceptional"}:
        d.ellipse([cx - 9 * scale, cy - 9 * scale, cx + 9 * scale, cy + 9 * scale], fill=SUN)
        for i in range(8):
            a = i * math.pi / 4
            x0 = cx + 12 * scale * math.cos(a)
            y0 = cy + 12 * scale * math.sin(a)
            x1 = cx + 17 * scale * math.cos(a)
            y1 = cy + 17 * scale * math.sin(a)
            d.line([(x0, y0), (x1, y1)], fill=SUN, width=max(2, int(2 * scale)))
        return

    if cond in {"clearnight", "night"}:
        d.ellipse([cx - 10 * scale, cy - 10 * scale, cx + 10 * scale, cy + 10 * scale], fill=NIGHT)
        d.ellipse([cx - 4 * scale, cy - 12 * scale, cx + 14 * scale, cy + 6 * scale], fill=BG)
        return

    if cond in {"partlycloudy", "partlycloudynight"}:
        if "night" in cond:
            d.ellipse([cx - 14 * scale, cy - 12 * scale, cx - 2 * scale, cy], fill=NIGHT)
            d.ellipse([cx - 10 * scale, cy - 14 * scale, cx + 2 * scale, cy - 2 * scale], fill=BG)
        else:
            d.ellipse([cx - 16 * scale, cy - 14 * scale, cx - 2 * scale, cy], fill=SUN)
        _cloud(d, cx + 2 * scale, cy + 2 * scale, scale * 0.95)
        return

    if cond in {"cloudy", "overcast"}:
        _cloud(d, cx, cy, scale * 1.05, fill=(140, 158, 175))
        return

    if cond in {"rainy", "pouring", "hail"}:
        _cloud(d, cx, cy - 4 * scale, scale)
        for i, dx in enumerate((-8, -2, 4, 10)):
            x0 = cx + dx * scale
            y0 = cy + 10 * scale + (i % 2) * 2 * scale
            d.line([(x0, y0), (x0 - 2 * scale, y0 + 8 * scale)], fill=RAIN, width=max(2, int(2 * scale)))
        return

    if cond in {"lightning", "thunderstorm"}:
        _cloud(d, cx, cy - 6 * scale, scale, fill=(130, 140, 170))
        bolt = [
            (cx - 2 * scale, cy + 2 * scale),
            (cx + 4 * scale, cy + 2 * scale),
            (cx - 1 * scale, cy + 10 * scale),
            (cx + 6 * scale, cy + 10 * scale),
            (cx - 4 * scale, cy + 20 * scale),
            (cx + 1 * scale, cy + 11 * scale),
            (cx - 5 * scale, cy + 11 * scale),
        ]
        d.polygon(bolt, fill=STORM)
        return

    if cond in {"snowy", "snowyrainy"}:
        _cloud(d, cx, cy - 4 * scale, scale, fill=(180, 195, 210))
        for dx, dy in ((-8, 10), (-1, 14), (7, 11), (2, 18), (-5, 18)):
            x, y = cx + dx * scale, cy + dy * scale
            d.ellipse([x - 2 * scale, y - 2 * scale, x + 2 * scale, y + 2 * scale], fill=SNOW)
        return

    if cond in {"fog", "windy"}:
        for i, yy in enumerate((-6, 0, 6, 12)):
            x0 = cx - 14 * scale + (i % 2) * 3 * scale
            d.line(
                [(x0, cy + yy * scale), (cx + 14 * scale, cy + yy * scale)],
                fill=FOG,
                width=max(2, int(2 * scale)),
            )
        return

    # Fallback: soft mint disc
    d.ellipse([cx - 10 * scale, cy - 10 * scale, cx + 10 * scale, cy + 10 * scale], outline=ARC, width=2)


def forecast_day_label(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(LOCAL_TZ)
        today = datetime.now(LOCAL_TZ).date()
        if dt.date() == today:
            return "Today"
        return dt.strftime("%a")
    except Exception:
        return "—"


def draw_weather_panel(
    d: ImageDraw.ImageDraw,
    x: int,
    y: int,
    width: int,
    weather: dict,
    f_temp,
    f_body,
    f_small,
    f_tiny,
) -> int:
    """Current conditions + multi-day forecast strip. Returns y below the panel."""
    if not weather.get("ok"):
        return y + 4

    unit = str(weather.get("unit") or "F")
    unit_sym = "°" if unit in {"F", "C", "°"} else unit
    cond = str(weather.get("condition") or "")
    temp = weather.get("temperature")
    hum = weather.get("humidity")
    wind = weather.get("wind_speed")

    panel_h = 86
    d.rounded_rectangle([x, y, x + width, y + panel_h], radius=10, fill=PANEL, outline=RULE, width=1)
    d.rounded_rectangle([x + 1, y + 1, x + width - 1, y + 4], radius=3, fill=RING)

    # Current block (left)
    icon_cx = x + 38
    icon_cy = y + 44
    draw_weather_icon(d, icon_cx, icon_cy, cond, size=34)

    tx = x + 72
    temp_s = f"{temp}{unit_sym}" if temp is not None else "--"
    d.text((tx, y + 10), temp_s, font=f_temp, fill=WHITE)
    d.text((tx, y + 42), cond.replace("-", " ").title() or "Weather", font=f_body, fill=STATUS)

    meta = []
    if hum is not None:
        meta.append(f"Hum {hum}%")
    if wind is not None:
        try:
            meta.append(f"Wind {float(wind):.0f}")
        except (TypeError, ValueError):
            meta.append(f"Wind {wind}")
    if meta:
        d.text((tx, y + 62), "  ·  ".join(meta), font=f_tiny, fill=MUTED)

    # Forecast columns
    forecast = list(weather.get("forecast") or [])[:5]
    if forecast:
        left = x + 280
        right = x + width - 12
        avail = max(120, right - left)
        col_w = avail // max(1, len(forecast))
        for i, day in enumerate(forecast):
            cx = left + i * col_w + col_w // 2
            label = forecast_day_label(str(day.get("datetime") or ""))
            lw = tw(d, label, f_tiny)
            d.text((cx - lw / 2, y + 8), label, font=f_tiny, fill=MUTED)
            draw_weather_icon(d, cx, y + 34, str(day.get("condition") or ""), size=22)
            hi = day.get("high")
            lo = day.get("low")
            if hi is not None and lo is not None:
                hl = f"{hi:.0f}°/{lo:.0f}°"
            elif hi is not None:
                hl = f"{hi:.0f}°"
            else:
                hl = "—"
            hw = tw(d, hl, f_tiny)
            d.text((cx - hw / 2, y + 52), hl, font=f_tiny, fill=CHROME)
            precip = day.get("precipitation")
            try:
                if precip is not None and float(precip) > 0:
                    ps = f"{float(precip):.2f}\""
                    pw = tw(d, ps, f_tiny)
                    d.text((cx - pw / 2, y + 68), ps, font=f_tiny, fill=RAIN)
            except (TypeError, ValueError):
                pass

    return y + panel_h + 10


def render(data: dict, w: int, h: int) -> Image.Image:
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)

    f_logo = font(FONT_BOLD, 56)
    f_title = font(FONT_SANS, 30)
    f_temp = font(FONT_BOLD, 28)
    f_sec = font(FONT_BOLD, 13)
    f_body = font(FONT_SANS, 13)
    f_small = font(FONT_SANS, 12)
    f_tiny = font(FONT_SANS, 11)

    margin = 28
    gap = 10
    y = 14

    # Header: HCC left, title centered, timestamp right
    title = "Hines Command Center"
    logo_h = th(d, "HCC", f_logo)
    title_h = th(d, title, f_title)
    d.text((margin, y), "HCC", font=f_logo, fill=LOGO)
    tw_title = tw(d, title, f_title)
    d.text(((w - tw_title) / 2, y + (logo_h - title_h) / 2), title, font=f_title, fill=CHROME)
    updated = str(data.get("updated") or "")
    uw = tw(d, updated, f_small)
    d.text((w - margin - uw, y + (logo_h - th(d, updated, f_small)) / 2), updated, font=f_small, fill=MUTED)
    y += logo_h + 16
    d.line([(margin, y), (w - margin, y)], fill=RING, width=2)
    y += 12

    y = draw_weather_panel(
        d, margin, y, w - 2 * margin, data.get("weather") or {},
        f_temp, f_body, f_small, f_tiny,
    )

    # Top row: SYSTEM | STORAGE | SERVICES
    col_w = (w - 2 * margin - 2 * gap) // 3
    top_h = 168
    host = str(data.get("hostname") or "hcc-node").upper()
    os_name = ((data.get("os") or {}).get("name")) or "Linux"
    uptime = str(data.get("uptime") or "?")
    load = str(data.get("load") or "?").split(",")[0].strip()
    mem = str(data.get("memory") or "?")
    kernel = str(data.get("kernel") or "")
    patches = (data.get("patches") or {})
    pending = patches.get("pending", 0)
    security = patches.get("security", 0)
    try:
        load_f = float(load)
    except ValueError:
        load_f = 0.0

    cx, cy, cw = draw_card(d, margin, y, col_w, top_h, "System", f_sec)
    cy = text_row(d, cx, cy, host, f_body, WHITE, cw)
    cy = text_row(d, cx, cy, fit(d, os_name, f_tiny, cw), f_tiny, CHROME, cw)
    cy = text_row(d, cx, cy, f"up {uptime}   load {load}", f_small, OK if load_f < 4 else WARN, cw)
    cy = text_row(d, cx, cy, mem, f_tiny, MUTED, cw)
    cy = text_row(d, cx, cy, f"kernel {kernel}", f_tiny, MUTED, cw)
    text_row(d, cx, cy, f"{pending} updates · {security} security", f_tiny, WARN if pending else OK, cw)

    cx, cy, cw = draw_card(d, margin + col_w + gap, y, col_w, top_h, "Storage", f_sec)
    pools = ((data.get("storage") or {}).get("pools")) or []
    if not pools:
        text_row(d, cx, cy, "No pools", f_body, MUTED, cw)
    for pool in pools[:4]:
        name = str(pool.get("name") or "?")
        health = str(pool.get("health") or "?")
        pct = float(pool.get("used_pct") or 0)
        free = pool.get("free_gb")
        label = f"{name}  {pct:.0f}%" + (f"  {free:.0f}G free" if free is not None else "")
        cy = kv_right(d, cx, cy, cw, label, health, f_tiny, f_tiny, WHITE, health_color(health))
        draw_bar(d, cx, cy, cw, 7, pct)
        cy += 11

    cx, cy, cw = draw_card(d, margin + 2 * (col_w + gap), y, col_w, top_h, "Services", f_sec)
    svc_map = {s.get("name"): s.get("state") for s in (data.get("services") or []) if s.get("name")}
    names = watch_names() + [n for n in ("docker", "smbd", "winbind") if n not in watch_names()]
    seen: set[str] = set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        state = str(svc_map.get(name) or "stopped")
        label = "OK" if state == "active" else state
        cy = kv_right(d, cx, cy, cw, name, label, f_small, f_tiny, WHITE, state_color(state))

    y += top_h + gap

    # One full-width Network card: Link | DNS/GW | VLANs | Pings
    ni = data.get("netinfo") or {}
    unifi = data.get("unifi") or {}
    half = (w - 2 * margin - gap) // 2
    net_h = 132
    cx, cy0, cw_all = draw_card(d, margin, y, w - 2 * margin, net_h, "Network", f_sec)
    col_gap = 18
    col_w = (cw_all - 3 * col_gap) // 4
    cols_x = [cx + i * (col_w + col_gap) for i in range(4)]

    # Column headers
    for i, title in enumerate(("Link", "DNS / Gateway", "VLANs", "Pings")):
        d.text((cols_x[i], cy0), title, font=f_tiny, fill=MUTED)
    cy_base = cy0 + th(d, "Link", f_tiny) + 6

    # Link
    x, cy, cw = cols_x[0], cy_base, col_w
    iface = str(ni.get("iface") or "?")
    link = str(ni.get("state") or "?")
    cidr = str(ni.get("cidr") or ni.get("ip") or "?")
    speed = ni.get("speed_mbps") or "?"
    duplex = str(ni.get("duplex") or "?")
    mtu = ni.get("mtu") or "?"
    rx = ni.get("rx_gb") or 0
    tx = ni.get("tx_gb") or 0
    rxe = int(ni.get("rx_errors") or 0)
    txe = int(ni.get("tx_errors") or 0)
    rxd = int(ni.get("rx_dropped") or 0)
    txd = int(ni.get("tx_dropped") or 0)
    tcp = ni.get("tcp_estab") or 0
    vpn = (ni.get("vpn") or {}).get("name") or "vpn"
    vpn_state = str((ni.get("vpn") or {}).get("state") or "?")
    cy = kv_right(d, x, cy, cw, iface, link, f_small, f_tiny, WHITE, state_color(link))
    cy = text_row(d, x, cy, cidr, f_tiny, CHROME, cw)
    cy = text_row(d, x, cy, f"{speed}Mb  {duplex}  MTU {mtu}", f_tiny, MUTED, cw)
    cy = text_row(d, x, cy, f"RX {rx}G  TX {tx}G  TCP {tcp}", f_tiny, CHROME, cw)
    err_c = WARN if (rxe + txe + rxd + txd) else OK
    cy = text_row(d, x, cy, f"err {rxe}/{txe}  drop {rxd}/{txd}", f_tiny, err_c, cw)
    text_row(d, x, cy, f"{vpn} {vpn_state}", f_tiny, state_color(vpn_state), cw)

    # DNS / Gateway
    x, cy, cw = cols_x[1], cy_base, col_w
    dns_ok = bool(ni.get("dns_ok"))
    cy = kv_right(d, x, cy, cw, "resolve", "OK" if dns_ok else "DOWN", f_small, f_tiny, WHITE, OK if dns_ok else BAD)
    for ping in list(ni.get("dns_pings") or [])[:4]:
        ip = str(ping.get("ip") or "?")
        ok = bool(ping.get("ok"))
        lat = ping.get("latency_ms")
        right = f"{float(lat):.0f}ms" if ok and lat is not None else ("DN" if not ok else "OK")
        cy = kv_right(d, x, cy, cw, ip, right, f_tiny, f_tiny, CHROME, OK if ok else BAD)
    gw = str(ni.get("gateway") or "?")
    pub = str(ni.get("public_ip") or "—")
    cy = text_row(d, x, cy, f"GW {gw}", f_tiny, MUTED, cw)
    text_row(d, x, cy, f"WAN {pub}", f_tiny, CHROME, cw)

    # VLANs
    x, cy, cw = cols_x[2], cy_base, col_w
    if unifi.get("ok"):
        vlans = list(unifi.get("vlans") or [])
        if not vlans:
            text_row(d, x, cy, "No VLANs", f_tiny, MUTED, cw)
        else:
            for vlan in vlans[:6]:
                vname = str(vlan.get("name") or "?").strip()
                vid = vlan.get("vlan")
                cy = kv_right(
                    d, x, cy, cw,
                    f"{vid} {vname}",
                    str(vlan.get("subnet") or ""),
                    f_tiny, f_tiny, WHITE, MUTED,
                )
    elif unifi.get("configured"):
        text_row(d, x, cy, "UniFi login failed", f_tiny, WARN, cw)
    else:
        text_row(d, x, cy, "No UniFi config", f_tiny, MUTED, cw)

    # Pings
    x, cy, cw = cols_x[3], cy_base, col_w
    pings = list(data.get("network") or [])
    if not pings:
        text_row(d, x, cy, "No targets", f_tiny, MUTED, cw)
    else:
        for ping in pings[:6]:
            label = str(ping.get("label") or ping.get("name") or "?")
            ok = bool(ping.get("ok"))
            lat = ping.get("latency_ms")
            right = f"{float(lat):.1f}ms" if ok and lat is not None else ("DOWN" if not ok else "OK")
            cy = kv_right(d, x, cy, cw, label, right, f_tiny, f_tiny, WHITE, OK if ok else BAD)

    # Subtle column dividers
    for i in range(1, 4):
        dx = cols_x[i] - col_gap // 2
        d.line([(dx, cy_base), (dx, y + net_h - 10)], fill=RULE, width=1)

    y += net_h + gap

    # Speedtest slim card
    st = (unifi.get("speedtest") or ni.get("speedtest") or {})
    st_h = 48
    cx, cy, cw = draw_card(d, margin, y, w - 2 * margin, st_h, "Speedtest", f_sec)
    if st.get("download_mbps") is not None or st.get("upload_mbps") is not None:
        when = st.get("when") or ""
        src = st.get("source") or ""
        stale = " · stale" if st.get("stale") else ""
        sline = (
            f"↓ {st.get('download_mbps', '?')} Mbps   "
            f"↑ {st.get('upload_mbps', '?')} Mbps   "
            f"ping {st.get('latency_ms', '?')} ms"
        )
        d.text((cx, cy), sline, font=f_small, fill=WHITE)
        meta = " · ".join(p for p in (src, when) if p) + stale
        if meta.strip(" ·"):
            d.text((cx + tw(d, sline, f_small) + 18, cy + 1), meta, font=f_tiny, fill=MUTED)
    else:
        text_row(d, cx, cy, "No speedtest yet", f_tiny, MUTED, cw)

    y += st_h + gap

    # Camera previews sit under Proxmox (full width). Prefer full Proxmox/Frigate
    # content height; shrink the preview strip into whatever space remains.
    previews = load_camera_previews(data) if PREVIEWS_ENABLED else []
    strip_w = w - 2 * margin

    inner_w = half - 2 * CARD_PAD
    probe = Image.new("RGB", (max(8, inner_w + 4), h), BG)
    pd = ImageDraw.Draw(probe)
    prox_body = paint_proxmox_body(pd, 0, 0, inner_w, data, f_tiny)
    frig_body = paint_frigate_home_body(pd, 0, 0, inner_w, data, f_tiny, f_small)
    cards_y = y
    floor = 18
    avail = max(60, h - cards_y - floor)
    prox_h = CARD_HEADER + prox_body + CARD_BOTTOM_PAD
    frig_h = CARD_HEADER + frig_body + CARD_BOTTOM_PAD
    row_h = max(prox_h, frig_h)
    strip_budget = 0
    if previews:
        strip_budget = max(0, avail - row_h - gap)
        # If content row alone overflows, shrink cards to leave a thin strip.
        if strip_budget < 70 and row_h + gap + 70 > avail:
            row_h = max(60, avail - gap - 70)
            prox_h = min(prox_h, row_h)
            frig_h = min(frig_h, row_h)
            strip_budget = max(0, avail - row_h - gap)
        strip_h = camera_preview_strip_height(strip_w, len(previews), f_tiny, max_h=strip_budget)
    else:
        strip_h = 0
        prox_h = min(prox_h, avail)
        frig_h = min(frig_h, avail)

    cx, cy, cw = draw_card(d, margin, cards_y, half, prox_h, "Proxmox", f_sec)
    paint_proxmox_body(d, cx, cy, cw, data, f_tiny)

    cx, cy, cw = draw_card(d, margin + half + gap, cards_y, half, frig_h, "Frigate / Home", f_sec)
    paint_frigate_home_body(d, cx, cy, cw, data, f_tiny, f_small)

    # Previews: full-width row(s) below the Proxmox/Frigate row (L→R, ≤8 per row).
    if previews and strip_h and strip_budget:
        strip_y = cards_y + max(prox_h, frig_h) + gap
        paint_camera_preview_strip(
            img, d, margin, strip_y, strip_w, previews, f_tiny, f_sec, max_h=strip_budget
        )

    d.line([(margin, h - 16), (w - margin, h - 16)], fill=RING, width=2)
    return img



def main() -> int:
    ap = argparse.ArgumentParser(description="HCC framebuffer dashboard")
    ap.add_argument("--status-file", type=Path, default=STATUS_FILE)
    ap.add_argument("--stdin", action="store_true", help="read JSON status from stdin")
    ap.add_argument("--png", type=Path, default=None, help="also write a PNG preview")
    args = ap.parse_args()

    data = load_data(args.status_file, args.stdin)
    w, h, bpp = fb_size()
    clear_tty()
    frame = render(data, w, h)
    if args.png:
        frame.save(args.png)
    blit_fb(frame, bpp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
