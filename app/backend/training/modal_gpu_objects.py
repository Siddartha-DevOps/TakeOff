"""
Cloud GPU training for the Model 2 symbol/object detector, on Modal.

Plain YOLOv8 detection (task="detect", not -seg) over objects_dataset.
SYMBOL_CLASSES — the SESYD/CubiCasa-icon-sourced appliance/MEP/circulation
set (see sesyd_to_yolo.py for dataset prep). See modal_gpu.py for the Model 1
room-segmentation analog and the rationale for training off Vercel entirely
(CLAUDE.md guardrail #2: heavy ML never runs inside a Vercel function/route).

One-time setup on the machine that launches training:
    pip install modal
    modal token new

Usage:
    cd app/backend
    modal run training/modal_gpu_objects.py
    modal run training/modal_gpu_objects.py --epochs 200 --run-name objects_v2

Expects the symbol dataset locally at datasets/symbols_yolo/, already split
into images/{train,val} + labels/{train,val} (sesyd_to_yolo.py only produces
the flat pool — split it first, e.g. with ultralytics.data.utils.autosplit).
"""

from __future__ import annotations

import sys
from pathlib import Path

import modal

sys.path.insert(0, str(Path(__file__).resolve().parent))
from objects_dataset import build_objects_yaml  # noqa: E402

VOLUME_NAME = "takeoff-data"
DATASET_VOLUME_PATH = "/data/datasets/symbols_yolo"
RUNS_VOLUME_PATH = "/data/models/objects/runs"

image = modal.Image.debian_slim(python_version="3.11").pip_install(
    "ultralytics==8.2.0",
    "torch==2.3.1",
    "torchvision==0.18.1",
)

app = modal.App("takeoff-objects-det", image=image)
volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)


@app.function(gpu="A10G", volumes={"/data": volume}, timeout=6 * 60 * 60)
def train_yolo(config: dict) -> str:
    """Fine-tune YOLOv8 detection for the symbol/object classes. Executes on Modal's GPU."""
    from ultralytics import YOLO

    volume.reload()  # pick up the dataset main() just uploaded

    data_yaml = Path(config["data_yaml"])
    if not data_yaml.exists():
        data_yaml = build_objects_yaml(data_yaml.parent)

    model = YOLO(config["base_model"])
    results = model.train(
        data=str(data_yaml),
        epochs=config["epochs"],
        imgsz=config["imgsz"],
        batch=config["batch"],
        task="detect",
        project=RUNS_VOLUME_PATH,
        name=config["run_name"],
        exist_ok=True,
        degrees=0,
        flipud=0,
        fliplr=0.3,
        conf=0.2,
        box=10.0,  # small-object precision (symbols are ~20-60px)
    )

    best = Path(results.save_dir) / "weights" / "best.pt"
    volume.commit()
    return str(best)


@app.local_entrypoint()
def main(
    data_dir: str = "datasets/symbols_yolo",
    base_model: str = "yolov8m.pt",
    epochs: int = 300,
    imgsz: int = 1280,
    batch: int = 16,
    run_name: str = "objects_v1",
) -> None:
    # Upload dataset to the Modal volume first.
    volume.put_directory(data_dir, DATASET_VOLUME_PATH)

    # Launch training.
    result = train_yolo.remote({
        "base_model": base_model,
        "data_yaml": f"{DATASET_VOLUME_PATH}/objects.yaml",
        "epochs": epochs,
        "imgsz": imgsz,
        "batch": batch,
        "run_name": run_name,
    })
    print(f"Best weights at: {result}")
