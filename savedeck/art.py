"""Cover-art loading with a disk cache (blocking; call from worker threads).

Handles Steam CDN / Epic URLs, data URLs (Cartridge manual entries) and
local file paths. Images are downscaled once to the tile size and stored in
%APPDATA%/SaveDeck/cache, so after the first run tiles paint instantly.
"""
from __future__ import annotations

import base64
import hashlib
import os
import re

import requests

from . import home_dir

UA = {"User-Agent": "SaveDeck/1.0"}


def cache_dir() -> str:
    d = os.path.join(home_dir(), "cache")
    os.makedirs(d, exist_ok=True)
    return d


def fetch_art(entry: dict, size: tuple) -> str:
    """Return a local file path to a resized image, or '' if unavailable."""
    src = entry.get("thumbnail")
    if not src:
        return ""
    key = hashlib.sha1(src.encode("utf-8", "replace")).hexdigest()[:16]
    out = os.path.join(cache_dir(), f"{key}_{size[0]}x{size[1]}.png")
    if os.path.isfile(out):
        return out

    raw = None
    m = re.match(r"data:image/[^;]+;base64,(.+)", src, re.DOTALL)
    if m:
        try:
            raw = base64.b64decode(m.group(1))
        except Exception:
            return ""
    elif re.match(r"^https?://", src):
        try:
            r = requests.get(src, timeout=10, headers=UA)
            if r.ok:
                raw = r.content
        except Exception:
            return ""
    elif os.path.isfile(src):
        try:
            with open(src, "rb") as f:
                raw = f.read()
        except OSError:
            return ""
    if not raw:
        return ""
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        img.thumbnail(size, Image.LANCZOS)
        tmp = out + ".tmp"
        img.save(tmp, "PNG")
        os.replace(tmp, out)
        return out
    except Exception:
        return ""


def tile_image(entry: dict, size: tuple) -> str:
    """Cover art or a generated placeholder — always returns a local path."""
    key = hashlib.sha1((entry.get("id") or entry.get("name") or "x")
                       .encode("utf-8")).hexdigest()[:16]
    ph = os.path.join(cache_dir(), f"ph_{key}_{size[0]}x{size[1]}.png")
    if os.path.isfile(ph):
        return ph
    p = fetch_art(entry, size)
    if p:
        return p
    placeholder_png(ph, size, entry.get("name", "?"))
    return ph if os.path.isfile(ph) else ""


def placeholder_png(path: str, size: tuple, name: str) -> str:
    """Generate a terminal-styled placeholder tile (cartridge glyph + initial)."""
    try:
        from PIL import Image, ImageDraw
        img = Image.new("RGB", size, (15, 23, 18))
        d = ImageDraw.Draw(img)
        w, h = size
        d.rectangle([8, 8, w - 9, h - 9], outline=(29, 47, 34), width=1)
        # cartridge body
        cx0, cy0, cx1, cy1 = w // 2 - 40, h // 2 - 55, w // 2 + 40, h // 2 + 55
        d.rectangle([cx0, cy0, cx1, cy1], outline=(74, 222, 128), width=2)
        d.rectangle([cx0 + 12, cy0 + 10, cx1 - 12, cy0 + 34], outline=(74, 222, 128), width=1)
        for i in range(4):  # connector notches
            x = cx0 + 12 + i * 14
            d.line([x, cy0 + 14, x, cy0 + 30], fill=(74, 222, 128), width=2)
        d.line([cx0, cy1 - 18, cx1, cy1 - 18], fill=(74, 222, 128), width=1)
        label = (name or "?").strip()[:1].upper() or "?"
        d.text((w // 2 - 5, cy1 - 13), label, fill=(127, 174, 140))
        tmp = path + ".tmp"
        img.save(tmp, "PNG")
        os.replace(tmp, path)
        return path
    except Exception:
        return ""

