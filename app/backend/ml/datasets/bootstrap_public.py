"""
Bootstrap a space-segmentation training set from PUBLIC floor-plan datasets.

The correction flywheel (``ml/training/export_corrections.py``) only produces
labels once users start correcting AI output — a cold start. This module warms it
up: it remaps room polygons from public, permissively-licensed floor-plan corpora
(CubiCasa5K, RPLAN, Structured3D) onto Takeoff's space-class list and writes them
in Ultralytics YOLOv8-seg format, so ``training/train_yolov8_seg.py`` can fine-tune
a first space model before a single hand-labeled Takeoff sheet exists.

Space classes here mirror the room labels in ``ai/inference_api.py`` (living /
bedroom / bathroom / kitchen / balcony / stair / storage). Symbols (doors,
windows, MEP) are a separate model with its own class list in
``training/train_yolov8_seg.py``.

The remap + label-formatting functions are pure and unit-tested; the filesystem
walk over an extracted dataset (``build_dataset_from_public``) is the orchestration
run on a training box.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional, Sequence

# Takeoff space classes (index = YOLO class id). Order is stable and must match
# what training/eval expect; append new classes, never reorder.
SPACE_CLASSES: list[str] = [
    "living", "bedroom", "bathroom", "kitchen", "balcony", "stair", "storage",
]
_CLASS_ID = {name: i for i, name in enumerate(SPACE_CLASSES)}

# CubiCasa5K room categories -> Takeoff space class. Categories not present here
# (Wall, Window, Door, Railing, Background, Undefined, ...) are intentionally
# dropped: they are either a different model's job (symbols) or not a space.
CUBICASA_TO_TAKEOFF: dict[str, str] = {
    "LivingRoom": "living", "Living": "living", "Room": "living",
    "DraughtRoom": "living", "Den": "living",
    "Bedroom": "bedroom", "MasterBedroom": "bedroom", "ChildRoom": "bedroom",
    "Bath": "bathroom", "Bathroom": "bathroom", "Sauna": "bathroom",
    "Kitchen": "kitchen", "Pantry": "kitchen",
    "Balcony": "balcony", "Outdoor": "balcony", "Terrace": "balcony",
    "Stairs": "stair", "Staircase": "stair", "Landing": "stair",
    "Storage": "storage", "Closet": "storage", "WalkIn": "storage",
    "Garage": "storage", "Utility": "storage",
}


def remap_label(source_label: str, mapping: Optional[dict[str, str]] = None) -> Optional[str]:
    """Map a source dataset room label to a Takeoff space class, or None to drop.

    Matching is case-insensitive and ignores spaces/underscores, so
    ``"Living Room"``, ``"living_room"`` and ``"LivingRoom"`` all resolve.
    """
    table = mapping if mapping is not None else CUBICASA_TO_TAKEOFF
    norm = {k.lower().replace(" ", "").replace("_", ""): v for k, v in table.items()}
    return norm.get(source_label.lower().replace(" ", "").replace("_", ""))


def class_id(space_class: str) -> int:
    """YOLO class id for a Takeoff space class name."""
    try:
        return _CLASS_ID[space_class]
    except KeyError:
        raise ValueError(f"unknown space class {space_class!r}; expected one of {SPACE_CLASSES}")


def normalize_ring(ring: Sequence[Sequence[float]], img_w: float, img_h: float) -> list[float]:
    """Flatten a polygon ring to YOLO-seg normalized coords (x1 y1 x2 y2 ...).

    Coordinates are clamped to [0, 1] and rounded, matching the convention in
    ``ml/training/export_corrections.normalize_ring`` so datasets from either
    source are byte-compatible for the trainer.
    """
    if img_w <= 0 or img_h <= 0:
        raise ValueError("image dimensions must be positive")
    out: list[float] = []
    for x, y in ring:
        out.append(min(1.0, max(0.0, x / img_w)))
        out.append(min(1.0, max(0.0, y / img_h)))
    return [round(v, 6) for v in out]


def polygon_to_seg_line(
    source_label: str,
    ring: Sequence[Sequence[float]],
    img_w: float,
    img_h: float,
    mapping: Optional[dict[str, str]] = None,
) -> Optional[str]:
    """One YOLO-seg label line for a room polygon, or None if its class is dropped.

    A valid polygon needs at least 3 points; degenerate rings return None.
    """
    space = remap_label(source_label, mapping)
    if space is None:
        return None
    if len(ring) < 3:
        return None
    coords = normalize_ring(ring, img_w, img_h)
    return " ".join([str(class_id(space)), *(f"{c:g}" for c in coords)])


def build_label_lines(
    rooms: Iterable[tuple[str, Sequence[Sequence[float]]]],
    img_w: float,
    img_h: float,
    mapping: Optional[dict[str, str]] = None,
) -> list[str]:
    """Build all seg label lines for one image; silently skips dropped/degenerate rooms."""
    lines: list[str] = []
    for label, ring in rooms:
        line = polygon_to_seg_line(label, ring, img_w, img_h, mapping)
        if line is not None:
            lines.append(line)
    return lines


def data_yaml_text(dataset_dir: Path) -> str:
    """Ultralytics data.yaml text for the space classes (matches train script format)."""
    names = "\n".join(f"  {i}: {name}" for i, name in enumerate(SPACE_CLASSES))
    return (
        f"path: {dataset_dir}\n"
        f"train: images/train\n"
        f"val: images/val\n"
        f"nc: {len(SPACE_CLASSES)}\n"
        f"names:\n{names}\n"
    )


def build_dataset_from_public(
    samples: Iterable[dict],
    out_dir: Path,
    *,
    val_every: int = 5,
    mapping: Optional[dict[str, str]] = None,
) -> dict:
    """Write a YOLOv8-seg dataset from public floor-plan samples (training box).

    Each sample: ``{"image_id", "image": np.ndarray|None, "width", "height",
    "rooms": [(label, ring), ...]}``. Every ``val_every``-th sample goes to val.
    Requires cv2 only when an in-memory image is provided; label/yaml writing is
    dependency-free. Returns a summary of what was written.
    """
    out = Path(out_dir)
    for split in ("train", "val"):
        (out / f"images/{split}").mkdir(parents=True, exist_ok=True)
        (out / f"labels/{split}").mkdir(parents=True, exist_ok=True)

    written = {"train": 0, "val": 0, "rooms": 0, "dropped_images": 0}
    for idx, s in enumerate(samples):
        lines = build_label_lines(s["rooms"], s["width"], s["height"], mapping)
        if not lines:  # no in-vocabulary rooms -> nothing to learn from
            written["dropped_images"] += 1
            continue
        split = "val" if (idx % val_every == 0) else "train"
        stem = str(s["image_id"])
        (out / f"labels/{split}/{stem}.txt").write_text("\n".join(lines))
        if s.get("image") is not None:
            import cv2  # lazy: only needed to persist raster images
            cv2.imwrite(str(out / f"images/{split}/{stem}.png"), s["image"])
        written[split] += 1
        written["rooms"] += len(lines)

    (out / "data.yaml").write_text(data_yaml_text(out))
    return written
