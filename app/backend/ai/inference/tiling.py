"""
Tiled inference for large construction drawings (large-drawing optimization).

A single E-size architectural sheet at 300 DPI is ~10000×7000 px — too large to
feed a detector at native resolution without either downsampling away the small
symbols (doors, outlets) or blowing up GPU memory. The standard fix is to slide
an overlapping window over the sheet, detect per tile, then merge: offset each
tile's detections back to page coordinates and run a global NMS so a wall or room
straddling a seam isn't double-counted.

The grid/offset/merge logic is pure and unit-tested; ``run_tiled`` is the thin
orchestration that calls an injected per-tile ``runner`` (the real model on the
GPU box).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

from .confidence import nms


@dataclass(frozen=True)
class Tile:
    """A crop window in page-pixel coordinates: [x0, y0) .. [x1, y1)."""
    x0: int
    y0: int
    x1: int
    y1: int

    @property
    def width(self) -> int:
        return self.x1 - self.x0

    @property
    def height(self) -> int:
        return self.y1 - self.y0


def tile_grid(width: int, height: int, tile: int = 1280, overlap: int = 128) -> list[Tile]:
    """Cover a ``width``×``height`` page with overlapping ``tile``×``tile`` windows.

    Overlap ensures objects on a seam appear whole in at least one tile. The last
    row/column is clamped to the page edge (so tiles never exceed the image and
    the final tile isn't undersized off-page).
    """
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")
    if tile <= 0:
        raise ValueError("tile must be positive")
    if not 0 <= overlap < tile:
        raise ValueError("overlap must satisfy 0 <= overlap < tile")

    step = tile - overlap
    tiles: list[Tile] = []

    def starts(extent: int) -> list[int]:
        if extent <= tile:
            return [0]
        pts = list(range(0, extent - tile + 1, step))
        if pts[-1] != extent - tile:
            pts.append(extent - tile)  # clamp final tile flush to the edge
        return pts

    for y0 in starts(height):
        for x0 in starts(width):
            tiles.append(Tile(x0, y0, min(x0 + tile, width), min(y0 + tile, height)))
    return tiles


def translate_detection(det: dict, dx: int, dy: int) -> dict:
    """Shift a detection's bbox/polygon from tile-local to page coordinates."""
    out = copy.deepcopy(det)
    if "bbox" in out and out["bbox"] is not None:
        x1, y1, x2, y2 = out["bbox"]
        out["bbox"] = [x1 + dx, y1 + dy, x2 + dx, y2 + dy]
    if out.get("polygon"):
        out["polygon"] = [[x + dx, y + dy] for x, y in out["polygon"]]
    return out


def merge_tiled_detections(
    detections: Sequence[dict],
    iou_thr: float = 0.45,
    *,
    label_key: str = "label",
    score_key: str = "confidence",
) -> list[dict]:
    """De-duplicate detections pooled from overlapping tiles, per class.

    NMS is run within each class independently (a door overlapping a room is not
    a duplicate), keeping the highest-confidence instance of each real object.
    """
    by_class: dict = {}
    for d in detections:
        by_class.setdefault(d.get(label_key), []).append(d)

    merged: list[dict] = []
    for _, group in by_class.items():
        boxes = [d.get("bbox", [0, 0, 0, 0]) for d in group]
        scores = [d.get(score_key, 0.0) or 0.0 for d in group]
        for i in nms(boxes, scores, iou_thr):
            merged.append(group[i])
    return merged


def run_tiled(
    image,
    runner: Callable[["object", Tile], list[dict]],
    *,
    tile: int = 1280,
    overlap: int = 128,
    iou_thr: float = 0.45,
    size: Optional[tuple[int, int]] = None,
) -> list[dict]:
    """Run ``runner`` over every tile and merge the results into page space.

    ``runner(crop, tile)`` returns tile-local detection dicts; this offsets them
    to page coordinates and NMS-merges across seams. ``image`` is any array-like
    supporting ``image[y0:y1, x0:x1]`` (e.g. a NumPy raster); ``size`` overrides
    the (width, height) if the image type doesn't expose ``.shape``.
    """
    if size is not None:
        width, height = size
    else:
        h, w = image.shape[:2]
        width, height = w, h

    pooled: list[dict] = []
    for t in tile_grid(width, height, tile=tile, overlap=overlap):
        crop = image[t.y0:t.y1, t.x0:t.x1]
        for det in runner(crop, t):
            pooled.append(translate_detection(det, t.x0, t.y0))
    return merge_tiled_detections(pooled, iou_thr=iou_thr)
