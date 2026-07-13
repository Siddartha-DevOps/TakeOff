"""
Cloud GPU training for room-*type* segmentation, on Modal.

SAM2 (zero-shot, Phase 1 MVP) gives room shapes but no label — every mask
looks the same to it. This fine-tunes YOLOv8-seg on labeled floor plans
(CubiCasa5K + CVAT/Label Studio annotations) so it also predicts one of the
9 room types the app tracks (see ai/detection_engine.CLASS_NAMES, ids 0-8;
class list mirrored in rooms_dataset.ROOM_CLASSES). Training runs on a Modal
A10G — never locally inside this repo's CI, and never inside a Vercel
function/route (CLAUDE.md guardrail #2: heavy ML stays off Vercel).

One-time setup on the machine that launches training:
    pip install modal
    modal token new

Usage:
    cd app/backend
    modal run training/modal_gpu.py
    modal run training/modal_gpu.py --epochs 50 --imgsz 1280 --run-name rooms_v2
    # ~2-4 hours on an A10G with a CubiCasa5K-sized dataset.

Expects the room dataset locally at datasets/rooms_yolo/ (see rooms_dataset.py
for the exact layout) — main() uploads it to a persistent Modal volume before
training, and prints the trained weights path on completion.
"""

from __future__ import annotations

import sys
from pathlib import Path

import modal

# Import the sibling pure-Python module by path rather than relying on the
# caller's sys.path / package context — `modal run` may invoke this file
# either as a script or as part of the `training` package depending on cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from rooms_dataset import build_rooms_yaml  # noqa: E402

VOLUME_NAME = "takeoff-data"
DATASET_VOLUME_PATH = "/data/datasets/rooms_yolo"
RUNS_VOLUME_PATH = "/data/models/rooms/runs"

image = modal.Image.debian_slim(python_version="3.11").pip_install(
    "ultralytics==8.2.0",
    "torch==2.3.1",
    "torchvision==0.18.1",
)

app = modal.App("takeoff-rooms-seg", image=image)
volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)


@app.function(gpu="A10G", volumes={"/data": volume}, timeout=6 * 60 * 60)
def train_yolo(config: dict) -> str:
    """Fine-tune YOLOv8-seg for room-type segmentation. Executes on Modal's GPU."""
    from ultralytics import YOLO

    volume.reload()  # pick up the dataset main() just uploaded

    data_yaml = Path(config["data_yaml"])
    if not data_yaml.exists():
        data_yaml = build_rooms_yaml(data_yaml.parent)

    model = YOLO(config["base_model"])
    results = model.train(
        data=str(data_yaml),
        epochs=config["epochs"],
        imgsz=config["imgsz"],
        batch=config["batch"],
        task="segment",
        project=RUNS_VOLUME_PATH,
        name=config["run_name"],
        exist_ok=True,
        # Blueprint-specific augmentation: floor plans are always upright.
        degrees=0,
        flipud=0,
        fliplr=0.3,  # a mirrored floor plan is still a valid floor plan
    )

    best = Path(results.save_dir) / "weights" / "best.pt"
    volume.commit()
    return str(best)


@app.local_entrypoint()
def main(
    data_dir: str = "datasets/rooms_yolo",
    base_model: str = "yolov8x-seg.pt",  # largest YOLOv8 seg model
    epochs: int = 100,
    imgsz: int = 1024,  # floor plans need high res
    batch: int = 4,  # fits in 24GB A10G
    run_name: str = "rooms_v1",
) -> None:
    # Upload dataset to the Modal volume first.
    volume.put_directory(data_dir, DATASET_VOLUME_PATH)

    # Launch training.
    result = train_yolo.remote({
        "base_model": base_model,
        "data_yaml": f"{DATASET_VOLUME_PATH}/rooms.yaml",
        "epochs": epochs,
        "imgsz": imgsz,
        "batch": batch,
        "run_name": run_name,
    })
    print(f"Best weights at: {result}")
