"""
TakeOff.ai — Tiled pyramid rendering (Deep Zoom Image).

Closes memory/TOGAL_PARITY_REAUDIT.md #11: "No tiled rendering (react-pdf ->
OOM on large sheets). Build: OpenSeadragon/Pixi pyramid tiling."

DrawingRenderer.jsx used to load a drawing's *entire* rasterized resolution
into one <canvas> (raster images) or hand the whole PDF page to PDF.js at a
fixed render scale (PDFs) — a multi-thousand-pixel architectural sheet
allocates tens/hundreds of MB of canvas memory up front, regardless of how
much of it is actually visible on screen. This generates a standard Deep
Zoom Image tile pyramid instead: every zoom level downsampled and sliced
into small tiles, so OpenSeadragon (frontend) only ever fetches the handful
of tiles actually on screen at the current zoom, however large the source
sheet is.

Reuses ai/preprocessing.py's load_drawing() for the raster source (same
BGR-numpy convention, same TARGET_DPI, as drawing_compare.py and
clip_embeddings.py) — so PDFs and raster images (PNG/JPG/TIFF) go through
one unified tiling path, and the DZI's finest level is pixel-for-pixel the
same raster the AI/scale pipeline already measures against. PIL (image
resize/crop) lives in app/requirements.txt's heavy stack per CLAUDE.md §2,
same as every other CV-touching module in this backend — optional here
too, unavailable cleanly signals rather than crashing.
"""

import json
import math
import os
import sys
from typing import Optional

DEFAULT_TILE_SIZE = 254   # OpenSeadragon/DZI convention: 256px tile minus 2*1px overlap
DEFAULT_OVERLAP = 1
DEFAULT_FORMAT = "jpeg"
META_FILENAME = "meta.json"


def _ensure_ai_on_path():
    ai_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai")
    if ai_dir not in sys.path:
        sys.path.insert(0, ai_dir)


def tiling_available() -> bool:
    try:
        from PIL import Image  # noqa: F401
        return True
    except ImportError:
        return False


def _max_level(width: int, height: int) -> int:
    return int(math.ceil(math.log2(max(width, height, 1))))


def dzi_descriptor(width: int, height: int, tile_size: int = DEFAULT_TILE_SIZE,
                    overlap: int = DEFAULT_OVERLAP, fmt: str = DEFAULT_FORMAT) -> str:
    """Standard Deep Zoom Image XML descriptor — not consumed by this app's
    own frontend (it uses the JSON meta below via a custom OpenSeadragon
    tileSource instead), written alongside the tiles for interop with any
    other DZI-compatible viewer/tool."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Image TileSize="{tile_size}" Overlap="{overlap}" Format="{fmt}" '
        'xmlns="http://schemas.microsoft.com/deepzoom/2008">'
        f'<Size Width="{width}" Height="{height}"/>'
        '</Image>'
    )


def tile_meta_path(output_dir: str) -> str:
    return os.path.join(output_dir, META_FILENAME)


def read_tile_meta(output_dir: str) -> Optional[dict]:
    path = tile_meta_path(output_dir)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def tile_path(output_dir: str, level: int, col: int, row: int, fmt: str = DEFAULT_FORMAT) -> str:
    ext = "jpg" if fmt == "jpeg" else fmt
    return os.path.join(output_dir, str(level), f"{col}_{row}.{ext}")


def generate_tile_pyramid(
    source_path: str,
    output_dir: str,
    page_number: int = 0,
    tile_size: int = DEFAULT_TILE_SIZE,
    overlap: int = DEFAULT_OVERLAP,
    fmt: str = DEFAULT_FORMAT,
) -> dict:
    """
    Rasterizes `source_path` (PDF page or image) and writes a full DZI tile
    pyramid under `output_dir`: {output_dir}/{level}/{col}_{row}.{ext} for
    every level from 0 (coarsest) up to the source's native resolution,
    plus dzi.xml and meta.json. Returns the same dict written to meta.json.

    Idempotent: safe to re-run (overwrites existing tiles for this drawing).
    """
    import cv2
    from PIL import Image

    _ensure_ai_on_path()
    from preprocessing import load_drawing

    img_bgr = load_drawing(source_path, page_number=page_number)
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    full = Image.fromarray(img_rgb)
    width, height = full.size

    max_level = _max_level(width, height)
    os.makedirs(output_dir, exist_ok=True)
    ext = "jpg" if fmt == "jpeg" else fmt

    for level in range(max_level, -1, -1):
        scale = 2 ** (level - max_level)
        level_w = max(1, round(width * scale))
        level_h = max(1, round(height * scale))
        level_img = full if level == max_level else full.resize((level_w, level_h), Image.LANCZOS)
        if level_img.mode != "RGB":
            level_img = level_img.convert("RGB")

        level_dir = os.path.join(output_dir, str(level))
        os.makedirs(level_dir, exist_ok=True)

        cols = math.ceil(level_w / tile_size)
        rows = math.ceil(level_h / tile_size)
        for row in range(rows):
            for col in range(cols):
                x0, y0 = col * tile_size, row * tile_size
                x1, y1 = min(x0 + tile_size, level_w), min(y0 + tile_size, level_h)
                # DZI overlap convention: expand by `overlap` px on any edge
                # that isn't already at the image boundary.
                bx0 = x0 - overlap if col > 0 else x0
                by0 = y0 - overlap if row > 0 else y0
                bx1 = x1 + overlap if x1 < level_w else x1
                by1 = y1 + overlap if y1 < level_h else y1
                tile = level_img.crop((bx0, by0, bx1, by1))
                save_kwargs = {"quality": 85} if fmt == "jpeg" else {}
                tile.save(os.path.join(level_dir, f"{col}_{row}.{ext}"), **save_kwargs)

    meta = {
        "width": width, "height": height, "max_level": max_level,
        "tile_size": tile_size, "overlap": overlap, "format": fmt,
    }
    with open(tile_meta_path(output_dir), "w") as f:
        json.dump(meta, f)
    with open(os.path.join(output_dir, "dzi.xml"), "w") as f:
        f.write(dzi_descriptor(width, height, tile_size, overlap, fmt))

    return meta
