"""
Flywheel data export: CorrectionEvent -> YOLOv8-seg training dataset.

CLAUDE.md guardrail #5: every user correction is training data. This turns the
`correction_events` rows (accept / relabel / edit — the annotations the user
kept or fixed) into a labeled segmentation dataset that
`training/train_yolov8_seg.py` can fine-tune on, closing the loop
prediction -> correction -> retrain.

Geometry in a CorrectionEvent's `after` snapshot is plan-space pixels (the same
300-DPI space `Detection.geom` / `ai/preprocessing.py` use), so normalizing by
the rasterized page size gives YOLO's 0..1 polygon coordinates directly.

The label-formatting functions here are pure and unit-tested; the DB + page
rasterization live in `export_corrections_dataset`, which is the orchestration
run on a training box.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Optional

# Corrections that represent a *kept* (good or fixed) annotation — training
# positives. 'reject' means the AI was wrong: a hard negative, handled separately.
POSITIVE_ACTIONS = ("accept", "relabel", "edit")


def _ring_from_geometry(geometry) -> Optional[list[list[float]]]:
    """Coerce an annotation geometry into a polygon ring [[x, y], ...].

    Accepts a ring already, or a bbox [x1, y1, x2, y2] (count symbols) which is
    expanded into a rectangle ring.
    """
    if not geometry:
        return None
    # bbox form: flat 4-number list.
    if len(geometry) == 4 and all(isinstance(v, (int, float)) for v in geometry):
        x1, y1, x2, y2 = geometry
        return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
    # ring form: list of [x, y].
    ring = [[float(p[0]), float(p[1])] for p in geometry if len(p) >= 2]
    return ring if len(ring) >= 3 else None


def normalize_ring(ring, img_w: float, img_h: float) -> list[float]:
    """Flatten a ring to YOLO-seg normalized coords (x1 y1 x2 y2 ...), clamped 0..1."""
    if img_w <= 0 or img_h <= 0:
        raise ValueError("image dimensions must be positive")
    out: list[float] = []
    for x, y in ring:
        out.append(min(1.0, max(0.0, x / img_w)))
        out.append(min(1.0, max(0.0, y / img_h)))
    return [round(v, 6) for v in out]


def _label_of(after: dict) -> Optional[str]:
    """Class label from an `after` snapshot (meta.label, or top-level label/type)."""
    meta = after.get("meta") or {}
    return meta.get("label") or after.get("label") or after.get("class_label") or after.get("type")


def correction_to_seg_line(
    after: dict,
    class_map: dict[str, int],
    img_w: float,
    img_h: float,
) -> Optional[tuple[str, str]]:
    """One `after` snapshot -> (class_label, YOLO-seg label line), or None if unusable."""
    label = _label_of(after)
    if label is None or label not in class_map:
        return None
    ring = _ring_from_geometry(after.get("geometry"))
    if ring is None:
        return None
    coords = normalize_ring(ring, img_w, img_h)
    line = " ".join([str(class_map[label]), *(f"{c:g}" for c in coords)])
    return label, line


def build_label_lines(
    corrections: Iterable[dict],
    class_map: dict[str, int],
    img_w: float,
    img_h: float,
) -> list[str]:
    """Pure: turn a page's correction `after` snapshots into YOLO-seg label lines."""
    lines: list[str] = []
    for after in corrections:
        result = correction_to_seg_line(after, class_map, img_w, img_h)
        if result is not None:
            lines.append(result[1])
    return lines


def build_class_map(labels: Iterable[str]) -> dict[str, int]:
    """Deterministic label -> contiguous class id map (sorted for stability)."""
    return {label: i for i, label in enumerate(sorted(set(labels)))}


# ──────────────────────────────────────────────────────────────
# DB + rasterization orchestration (runs on a training box)
# ──────────────────────────────────────────────────────────────
def export_corrections_dataset(
    db,
    out_dir: str | Path,
    *,
    val_split: float = 0.2,
    actions: tuple[str, ...] = POSITIVE_ACTIONS,
    page_dpi: int = 300,
) -> dict:
    """Export kept corrections to a YOLOv8-seg dataset under `out_dir`.

    Groups CorrectionEvents by drawing, rasterizes each page once, and writes
    images/{train,val} + labels/{train,val} + data.yaml + class_map.json. Returns
    a summary dict. Best-effort per drawing: a page that can't be rasterized is
    skipped, not fatal.
    """
    import random

    import models  # local import: only needed on the training box
    from ai.preprocessing import load_drawing
    import cv2
    import storage

    out = Path(out_dir)
    for sub in ("images/train", "images/val", "labels/train", "labels/val"):
        (out / sub).mkdir(parents=True, exist_ok=True)

    events = (
        db.query(models.CorrectionEvent)
        .filter(models.CorrectionEvent.action.in_(actions))
        .filter(models.CorrectionEvent.drawing_id.isnot(None))
        .all()
    )

    # Group `after` snapshots by drawing.
    by_drawing: dict[int, list[dict]] = {}
    all_labels: list[str] = []
    for e in events:
        after = json.loads(e.after) if e.after else None
        if not after:
            continue
        label = _label_of(after)
        if label:
            all_labels.append(label)
        by_drawing.setdefault(e.drawing_id, []).append(after)

    class_map = build_class_map(all_labels)
    summary = {"drawings": 0, "labels": 0, "skipped": 0, "classes": len(class_map)}

    for drawing_id, corrections in by_drawing.items():
        drawing = db.query(models.Drawing).filter_by(id=drawing_id).first()
        if not drawing:
            summary["skipped"] += 1
            continue
        try:
            with storage.resolve_local_path(drawing.file_path) as local_path:
                img = load_drawing(local_path, page_number=getattr(drawing, "page_number", 0) or 0, dpi=page_dpi)
        except Exception:
            summary["skipped"] += 1
            continue

        h, w = img.shape[:2]
        lines = build_label_lines(corrections, class_map, w, h)
        if not lines:
            summary["skipped"] += 1
            continue

        split = "val" if random.random() < val_split else "train"
        stem = f"drawing_{drawing_id}"
        cv2.imwrite(str(out / f"images/{split}/{stem}.png"), img)
        (out / f"labels/{split}/{stem}.txt").write_text("\n".join(lines))
        summary["drawings"] += 1
        summary["labels"] += len(lines)

    # data.yaml + class_map for train_yolov8_seg.py / reproducibility.
    names = "\n".join(f"  {i}: {name}" for name, i in sorted(class_map.items(), key=lambda kv: kv[1]))
    (out / "data.yaml").write_text(
        f"path: {out}\ntrain: images/train\nval: images/val\n"
        f"nc: {len(class_map)}\nnames:\n{names}\n"
    )
    (out / "class_map.json").write_text(json.dumps(class_map, indent=2))
    return summary
