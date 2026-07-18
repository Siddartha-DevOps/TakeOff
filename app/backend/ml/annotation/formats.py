"""
Annotation format converters (mission item #4).

Annotators use different tools — CVAT/COCO, Label Studio, or raw YOLO — but the
trainer (``training/train_yolov8_seg.py``) eats exactly one format: Ultralytics
YOLO-seg (``class_id x1 y1 x2 y2 ...`` normalized polygon per line). This module
is the adapter layer that turns each external format into that, and validates
geometry on the way in.

Consistent with ``ml/datasets/bootstrap_public.normalize_ring`` and
``ml/training/export_corrections.normalize_ring`` so annotations from any
source — hand-labeled, public dataset, or user CorrectionEvents — produce
byte-compatible label files.

Pure stdlib — unit-tested, no cv2/torch.
"""

from __future__ import annotations

from typing import Iterable, Optional, Sequence


def validate_ring(ring: Sequence[Sequence[float]]) -> bool:
    """A ring is valid if it has ≥3 points, each an (x, y) pair."""
    if len(ring) < 3:
        return False
    return all(len(pt) == 2 for pt in ring)


def normalize_ring(ring: Sequence[Sequence[float]], img_w: float, img_h: float) -> list[float]:
    """Flatten a pixel-space ring to YOLO normalized coords (x1 y1 x2 y2 ...), clamped 0..1."""
    if img_w <= 0 or img_h <= 0:
        raise ValueError("image dimensions must be positive")
    out: list[float] = []
    for x, y in ring:
        out.append(min(1.0, max(0.0, x / img_w)))
        out.append(min(1.0, max(0.0, y / img_h)))
    return [round(v, 6) for v in out]


def yolo_seg_line(class_id: int, ring: Sequence[Sequence[float]], img_w: float, img_h: float) -> Optional[str]:
    """One YOLO-seg label line from a pixel-space polygon, or None if degenerate."""
    if not validate_ring(ring):
        return None
    coords = normalize_ring(ring, img_w, img_h)
    return " ".join([str(int(class_id)), *(f"{c:g}" for c in coords)])


def parse_yolo_seg_line(line: str) -> Optional[tuple[int, list[list[float]]]]:
    """Parse a YOLO-seg line back to ``(class_id, [[x,y], ...])`` normalized ring.

    Returns None for blank lines or malformed rows (odd coord count, < 3 points).
    """
    parts = line.split()
    if len(parts) < 7:  # class + at least 3 (x,y) pairs
        return None
    try:
        class_id = int(parts[0])
        coords = [float(v) for v in parts[1:]]
    except ValueError:
        return None
    if len(coords) % 2 != 0:
        return None
    ring = [[coords[i], coords[i + 1]] for i in range(0, len(coords), 2)]
    return (class_id, ring) if len(ring) >= 3 else None


def coco_to_yolo_seg(
    coco: dict,
    class_map: dict,
    *,
    only_category_ids: Optional[set] = None,
) -> dict:
    """Convert a COCO segmentation dict to per-image YOLO-seg label lines.

    ``class_map`` maps COCO ``category_id`` -> target YOLO class id. Images are
    keyed by file name. Polygons come from COCO's flat ``[x1,y1,x2,y2,...]``
    segmentation, normalized by each image's width/height. Categories absent from
    ``class_map`` (or filtered out by ``only_category_ids``) are dropped.
    """
    images = {img["id"]: img for img in coco.get("images", [])}
    out: dict = {}
    for ann in coco.get("annotations", []):
        cat = ann.get("category_id")
        if cat not in class_map:
            continue
        if only_category_ids is not None and cat not in only_category_ids:
            continue
        img = images.get(ann.get("image_id"))
        if not img:
            continue
        seg = ann.get("segmentation") or []
        flat = seg[0] if seg and isinstance(seg[0], list) else seg
        if not flat or len(flat) < 6:
            continue
        ring = [[flat[i], flat[i + 1]] for i in range(0, len(flat) - 1, 2)]
        line = yolo_seg_line(class_map[cat], ring, img["width"], img["height"])
        if line:
            out.setdefault(img["file_name"], []).append(line)
    return out


def label_studio_to_rings(task: dict) -> list[tuple[str, list[list[float]]]]:
    """Extract ``(label, pixel_ring)`` pairs from one Label Studio polygon task.

    Label Studio stores polygon points as percentages (0..100) of image size with
    ``original_width``/``original_height`` on each result; this converts them back
    to pixel coordinates so they can feed ``yolo_seg_line``.
    """
    rings: list[tuple[str, list[list[float]]]] = []
    for res in task.get("annotations", [{}])[0].get("result", []) if task.get("annotations") else []:
        val = res.get("value", {})
        pts = val.get("points")
        labels = val.get("polygonlabels") or val.get("labels") or []
        if not pts or not labels:
            continue
        w = res.get("original_width", 100)
        h = res.get("original_height", 100)
        ring = [[px / 100.0 * w, py / 100.0 * h] for px, py in pts]
        rings.append((labels[0], ring))
    return rings
