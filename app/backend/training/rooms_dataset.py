"""
Ultralytics dataset scaffolding for room-*type* segmentation.

SAM2 (zero-shot) gives room shapes for the Phase 1 MVP but has no notion of
room *type* — every mask looks the same to it. This module is the dataset-prep
half of closing that gap: it defines the 9 room classes and writes the
Ultralytics data.yaml consumed by both a local fine-tune and the Modal GPU
entrypoint (modal_gpu.py).

Deliberately pure Python — no torch/ultralytics/modal import — so it stays
importable (and unit-testable) without the GPU stack installed.

Dataset layout (Ultralytics segmentation format):

    datasets/rooms_yolo/
      images/{train,val}/*.png      # rasterized plan crops @ ~300 DPI
      labels/{train,val}/*.txt      # class_id x1 y1 x2 y2 ... (normalized polygon)
      rooms.yaml                    # written by build_rooms_yaml()

Source data: CubiCasa5K / RPLAN remapped to the class list below, plus
CVAT/Label Studio annotation of real plans.
"""

from __future__ import annotations

from pathlib import Path

# Keep in lock-step with ai/detection_engine.CLASS_NAMES ids 0-8 (its ROOM_CLASSES set).
ROOM_CLASSES = [
    "living", "bedroom", "kitchen", "bathroom",
    "dining", "office", "hallway", "closet", "utility",
]


def build_rooms_yaml(dataset_dir: str | Path) -> Path:
    """Write the Ultralytics data.yaml (rooms.yaml) for the 9 room classes."""
    dataset_dir = Path(dataset_dir)
    dataset_dir.mkdir(parents=True, exist_ok=True)

    names = "\n".join(f"  {i}: {name}" for i, name in enumerate(ROOM_CLASSES))
    yaml_text = (
        f"path: {dataset_dir}\n"
        f"train: images/train\n"
        f"val: images/val\n"
        f"nc: {len(ROOM_CLASSES)}\n"
        f"names:\n{names}\n"
    )
    out = dataset_dir / "rooms.yaml"
    out.write_text(yaml_text)
    return out
