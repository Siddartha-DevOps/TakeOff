"""
Dataset scaffolding for the appliance/MEP/circulation symbol *detector*
(bounding-box YOLOv8, task="detect" — not segmentation).

This is Model 2 in the phased build (room segmentation is Model 1, see
rooms_dataset.py). Its class list is sourced from SESYD + CubiCasa icon
annotations (see sesyd_to_yolo.py) and is deliberately broader than, and
DISTINCT FROM, ai/detect_symbols.SYMBOL_CLASS_NAMES — that list is the
door/window-*type* + plumbing/electrical set used by the segmentation-based
raster fallback (train_yolov8_seg.py). This one adds whole-appliance and
circulation classes (refrigerator, stove, stairs, elevator, ...) that the
segmentation model doesn't cover.

Pure Python — no PIL/ultralytics/modal import — so it stays importable (and
unit-testable) without the GPU/image stack.

Dataset layout expected (Ultralytics detection format):

    datasets/symbols_yolo/
      images/{train,val}/*.png
      labels/{train,val}/*.txt   # class_id cx cy w h (normalized)
      objects.yaml               # written by build_objects_yaml()

sesyd_to_yolo.py writes a flat images/ + labels/ (no train/val split yet,
since SESYD ships one big pool, not a pre-split one); split it before
training, e.g. with ultralytics' own `ultralytics.data.utils.autosplit`.
"""

from __future__ import annotations

from pathlib import Path

# Sourced from SESYD (Systems Evaluation SYnthetic Documents) + CubiCasa icon
# annotations. See sesyd_to_yolo.py's module docstring for the source format.
SYMBOL_CLASSES = [
    "door", "window", "sink", "toilet", "bathtub", "shower",
    "washer", "dryer", "refrigerator", "stove", "dishwasher",
    "water_heater", "outlet", "switch", "light", "hvac",
    "stairs", "elevator",
]


def bbox_to_yolo_line(
    cls_id: int, xmin: float, ymin: float, xmax: float, ymax: float, img_w: int, img_h: int,
) -> str:
    """Convert a pixel-space bbox to a YOLO detection label line: `class cx cy w h`, normalized."""
    if img_w <= 0 or img_h <= 0:
        raise ValueError(f"invalid image size: {img_w}x{img_h}")

    cx = ((xmin + xmax) / 2) / img_w
    cy = ((ymin + ymax) / 2) / img_h
    bw = (xmax - xmin) / img_w
    bh = (ymax - ymin) / img_h
    return f"{cls_id} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}"


def build_objects_yaml(dataset_dir: str | Path) -> Path:
    """Write the Ultralytics data.yaml (objects.yaml) for the symbol/object classes."""
    dataset_dir = Path(dataset_dir)
    dataset_dir.mkdir(parents=True, exist_ok=True)

    names = "\n".join(f"  {i}: {name}" for i, name in enumerate(SYMBOL_CLASSES))
    yaml_text = (
        f"path: {dataset_dir}\n"
        f"train: images/train\n"
        f"val: images/val\n"
        f"nc: {len(SYMBOL_CLASSES)}\n"
        f"names:\n{names}\n"
    )
    out = dataset_dir / "objects.yaml"
    out.write_text(yaml_text)
    return out
