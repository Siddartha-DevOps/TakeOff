"""
Golden-set builder (Phase 4).

The eval harness (``ml/eval/harness.py``) scores a model against a fixed
``golden.json`` of per-sheet samples carrying **ground truth and predictions**.
This module produces that file:

- **GT side** — from a held-out labeled split (YOLO-seg ``labels/<split>/*.txt``):
  room polygons (rings), symbol boxes per class, and derived quantities.
- **PRED side** — from a trained model's detections over the same images
  (``predictions_from_detections`` adapts ``ai.inference`` output to the harness
  schema). Running the model is GPU-side; the adapter + assembly are pure.

Emits exactly the shape ``harness.evaluate`` consumes:
    {"image_id", "rooms": {"gt": [ring], "pred": [ring]},
     "symbols": {"gt": {cls: [box]}, "pred": {cls: [{"score", "geom": box}]}},
     "quantities": {"gt": {k: n}, "pred": {k: n}}}

Pure stdlib + existing ml helpers; unit-tested end-to-end against the harness.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable, Optional

from ml.annotation.formats import parse_yolo_seg_line
from ml.datasets.acquire_cubicasa import png_dimensions
from ml.datasets.bootstrap_public import SPACE_CLASSES
from ml.preflight import parse_data_yaml


# --- geometry helpers (pure) ----------------------------------------------
def denormalize_ring(norm_ring, img_w: float, img_h: float) -> list[list[float]]:
    """YOLO-normalized ring [[nx,ny],...] -> pixel ring [[x,y],...]."""
    return [[nx * img_w, ny * img_h] for nx, ny in norm_ring]


def ring_bbox(ring) -> list[float]:
    """Axis-aligned [x1, y1, x2, y2] of a ring."""
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return [min(xs), min(ys), max(xs), max(ys)]


def polygon_area(ring) -> float:
    """Shoelace area of a closed ring (absolute value)."""
    n = len(ring)
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def default_symbol_classes(class_names: Iterable[str]) -> set:
    """Classes that are symbols (boxes) = everything not a known space class."""
    return set(class_names) - set(SPACE_CLASSES)


# --- ground truth from YOLO labels ----------------------------------------
def labels_to_gt(text: str, class_names, img_w: float, img_h: float,
                 *, symbol_classes: Optional[set] = None) -> dict:
    """Parse a YOLO-seg label file into a golden sample's GT side.

    Space classes become room rings; symbol classes become boxes; quantities are
    derived (room count, floor area in px², symbol count).
    """
    symbols_set = symbol_classes if symbol_classes is not None else default_symbol_classes(class_names)
    rooms: list = []
    symbols: dict = {}
    for line in text.splitlines():
        parsed = parse_yolo_seg_line(line)
        if not parsed:
            continue
        cid, norm_ring = parsed
        if cid < 0 or cid >= len(class_names):
            continue
        name = class_names[cid]
        ring = denormalize_ring(norm_ring, img_w, img_h)
        if name in symbols_set:
            symbols.setdefault(name, []).append(ring_bbox(ring))
        else:
            rooms.append(ring)
    quantities = {
        "room_count": len(rooms),
        "floor_area_px": round(sum(polygon_area(r) for r in rooms), 2),
        "symbol_count": sum(len(v) for v in symbols.values()),
    }
    return {"rooms": rooms, "symbols": symbols, "quantities": quantities}


def gt_sample(image_id: str, gt: dict) -> dict:
    """Wrap a GT dict into a golden sample (pred sides filled later)."""
    return {
        "image_id": image_id,
        "rooms": {"gt": gt["rooms"]},
        "symbols": {"gt": gt["symbols"]},
        "quantities": {"gt": gt["quantities"]},
    }


# --- predictions from model detections (pure adapter) ---------------------
def predictions_from_detections(detections, *, symbol_classes: set) -> dict:
    """Convert ``ai.inference`` detection dicts into the harness PRED shape.

    Detections: ``{"label","bbox","polygon"?,"confidence","area"?}``. Room-class
    detections become rings; symbol-class detections become scored boxes.
    """
    rooms: list = []
    symbols: dict = {}
    for d in detections:
        name = d.get("label")
        if name in symbol_classes:
            box = d.get("bbox")
            if box:
                symbols.setdefault(name, []).append(
                    {"score": float(d.get("confidence", 0.0)), "geom": box})
        else:
            ring = d.get("polygon") or (_bbox_to_ring(d["bbox"]) if d.get("bbox") else None)
            if ring:
                rooms.append(ring)
    quantities = {
        "room_count": len(rooms),
        "floor_area_px": round(sum(polygon_area(r) for r in rooms), 2),
        "symbol_count": sum(len(v) for v in symbols.values()),
    }
    return {"rooms": rooms, "symbols": symbols, "quantities": quantities}


def _bbox_to_ring(box) -> list[list[float]]:
    x1, y1, x2, y2 = box
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


def attach_predictions(samples: list, preds_by_image: dict) -> list:
    """Fill each sample's pred sides from ``{image_id: pred_dict}`` (missing -> empty)."""
    for s in samples:
        pred = preds_by_image.get(s["image_id"], {"rooms": [], "symbols": {}, "quantities": {}})
        s["rooms"]["pred"] = pred.get("rooms", [])
        s["symbols"]["pred"] = pred.get("symbols", {})
        s["quantities"]["pred"] = pred.get("quantities", {})
    return samples


# --- orchestration ---------------------------------------------------------
def read_class_names(data_yaml: str | Path) -> list:
    """Class names in id order from a dataset data.yaml."""
    return parse_data_yaml(Path(data_yaml).read_text())["names"]


def build_golden_gt(dataset_dir: str | Path, class_names, *, split: str = "val",
                    symbol_classes: Optional[set] = None) -> list:
    """Build GT-only golden samples from a dataset's labeled ``split``.

    Each label file is paired with its image (for pixel dimensions). Samples
    without a readable image are skipped.
    """
    root = Path(dataset_dir)
    labels_dir = root / "labels" / split
    images_dir = root / "images" / split
    samples: list = []
    for lbl in sorted(labels_dir.glob("*.txt")):
        img = images_dir / f"{lbl.stem}.png"
        if not img.is_file():
            continue
        try:
            w, h = png_dimensions(img)
        except ValueError:
            continue
        gt = labels_to_gt(lbl.read_text(), class_names, w, h, symbol_classes=symbol_classes)
        samples.append(gt_sample(lbl.stem, gt))
    return samples


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build a golden.json GT set from a labeled split")
    ap.add_argument("--dataset", required=True, help="dataset dir (data.yaml + images/labels)")
    ap.add_argument("--split", default="val")
    ap.add_argument("--out", required=True, help="output golden.json path")
    ap.add_argument("--predictions", default=None,
                    help="optional {image_id: pred} JSON to attach (else GT-only, ready for the GPU box)")
    args = ap.parse_args(argv)

    class_names = read_class_names(Path(args.dataset) / "data.yaml")
    samples = build_golden_gt(args.dataset, class_names, split=args.split)
    if args.predictions:
        preds = json.loads(Path(args.predictions).read_text())
        attach_predictions(samples, preds)

    Path(args.out).write_text(json.dumps(samples, indent=2))
    print(f"[golden] wrote {len(samples)} samples -> {args.out} "
          f"({'with predictions' if args.predictions else 'GT-only — attach predictions on the GPU box'})")
    return 0 if samples else 1


if __name__ == "__main__":
    sys.exit(main())
