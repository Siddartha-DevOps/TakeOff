"""
TakeOff.ai — Modal training stub (Phase 0 infra scaffolding).

CLAUDE.md §2 guardrail #2: "All heavy ML runs on a separate GPU service
(Modal / Replicate / RunPod / AWS GPU), invoked asynchronously" — this is
that service's training half, wrapping the repo's existing training
code so the actual training logic (hyperparameters, augmentation, loss
weights) has exactly one home; this file only adds the "run it on a
rented GPU" part.

Two training entry points exist in this repo and this file wraps both,
deliberately, rather than picking one:
  - app/backend/training/train_yolov8_seg.py::train() — the current,
    tested, live-loaded symbols trainer (ai/detect_symbols.py loads its
    output). train_symbols() below wraps this one.
  - app/training/train.py::train_yolo() / train_wall_classifier() — older,
    but still the only trainer in the repo for a dedicated *rooms-only*
    segmentation model and for the wall classifier CNN; no modern
    replacement for either exists yet. train_rooms() and
    train_wall_classifier() below wrap this one.

This module is infrastructure scaffolding: importing/deploying it defines
the App and its functions on Modal but does not start any training run.
Nothing here is invoked automatically — see the __main__ docstring below
for what a human has to type to actually kick off a job.

Setup this file assumes (not performed by this file itself):
    modal token set --token-id <id> --token-secret <secret>   # auth
    modal volume create takeoff-ai-datasets
    modal volume create takeoff-ai-models
    modal volume put takeoff-ai-datasets /local/path/to/rooms   rooms
    modal volume put takeoff-ai-datasets /local/path/to/symbols symbols
    modal secret create takeoff-ai-s3 \
        S3_BUCKET=... S3_ACCESS_KEY_ID=... S3_SECRET_ACCESS_KEY=... S3_REGION=...
    # (same env var names app/backend/storage.py already reads)

Deploy (does not run anything, just registers the App with Modal):
    modal deploy infra/modal_gpu.py

Kick off an actual training run (NOT executed as part of writing this
file — a deliberate, separate, billable step):
    modal run infra/modal_gpu.py --stage rooms   --epochs 200
    modal run infra/modal_gpu.py --stage symbols --epochs 300
    modal run infra/modal_gpu.py --stage walls
"""

from pathlib import Path

import modal

APP_NAME = "takeoff-ai-training"
REPO_ROOT = Path(__file__).resolve().parent.parent
TRAINING_SRC = REPO_ROOT / "app" / "training"                     # rooms + wall classifier (train_rooms, train_wall_classifier)
BACKEND_TRAINING_SRC = REPO_ROOT / "app" / "backend" / "training"  # symbols (train_symbols) — the live one ai/detect_symbols.py loads from
DATASETS_SRC = REPO_ROOT / "datasets"

app = modal.App(APP_NAME)

training_image = (
    modal.Image.debian_slim(python_version="3.11")
    # libgl1/libglib2.0-0: runtime deps for opencv-python (pulled in by ultralytics)
    .apt_install("libgl1", "libglib2.0-0")
    .pip_install(
        "ultralytics>=8.1.0",
        "torch",
        "torchvision",
        "boto3>=1.34.129",
        "loguru",
        "pyyaml",
    )
    .add_local_dir(str(TRAINING_SRC), remote_path="/root/training")
    .add_local_dir(str(BACKEND_TRAINING_SRC), remote_path="/root/backend_training")
    .add_local_dir(str(DATASETS_SRC), remote_path="/root/datasets")
)

# Two separate volumes: datasets are populated once via `modal volume put`
# and read many times; models are written by training runs and read by
# infra/modal_inference.py — keeping them separate avoids either job
# accidentally clobbering the other's contents on commit.
datasets_volume = modal.Volume.from_name("takeoff-ai-datasets", create_if_missing=True)
models_volume = modal.Volume.from_name("takeoff-ai-models", create_if_missing=True)

# Holds S3_BUCKET / S3_ACCESS_KEY_ID / S3_SECRET_ACCESS_KEY / S3_REGION /
# S3_ENDPOINT_URL — the exact env var names app/backend/storage.py reads,
# so a trained weight uploaded from here is immediately usable there.
s3_secret = modal.Secret.from_name("takeoff-ai-s3")

TRAIN_TIMEOUT_SECONDS = 8 * 60 * 60  # long-running fine-tunes; Modal has no Vercel-style 300s ceiling


def _stage_data_yaml(dataset_path: str, yaml_name: str) -> None:
    """
    train_yolo() (app/training/train.py) hardcodes `<dataset_path>/data.yaml`
    as its config path. The class-list source of truth is this repo's
    datasets/*.yaml (mounted read-only at /root/datasets), so copy it into
    place on the volume once rather than duplicating the class list here.
    """
    import shutil

    dest = Path(dataset_path) / "data.yaml"
    if not dest.exists():
        shutil.copy(f"/root/datasets/{yaml_name}", dest)


@app.function(
    image=training_image,
    gpu="A10G",
    volumes={"/data": datasets_volume, "/models": models_volume},
    secrets=[s3_secret],
    timeout=TRAIN_TIMEOUT_SECONDS,
)
def train_rooms(epochs: int = 200, model_size: str = "m", batch: int = 8, upload_to_s3: str = "") -> str:
    import sys
    sys.path.insert(0, "/root/training")
    import train as train_module

    _stage_data_yaml("/data/rooms", "rooms.yaml")
    best_path = train_module.train_yolo(
        dataset_path="/data/rooms", model_size=model_size, epochs=epochs, batch=batch, device="0",
    )

    dest = Path("/models") / "rooms_v1.pt"
    dest.write_bytes(Path(best_path).read_bytes())
    models_volume.commit()

    if upload_to_s3:
        train_module.upload_model_to_s3(str(dest), upload_to_s3)
    return str(dest)


@app.function(
    image=training_image,
    gpu="A10G",
    volumes={"/data": datasets_volume, "/models": models_volume},
    secrets=[s3_secret],
    timeout=TRAIN_TIMEOUT_SECONDS,
)
def train_symbols(epochs: int = 100, base_model: str = "yolov8s-seg.pt", batch: int = 16, upload_to_s3: str = "") -> str:
    """
    Wraps app/backend/training/train_yolov8_seg.py::train() — the same
    function app/backend/ml/training/retrain.py's flywheel calls — rather
    than app/training/train.py, so a Modal-trained checkpoint lands through
    the identical code path a local/CI-triggered retrain would use.
    base_model defaults to the 's' (small) variant — symbols are small
    objects (door/window/MEP icons at 30-60px), per AI_TRAINING_GUIDE.md
    Feature 5's own choice of yolov8s over yolov8m.

    Expects /data/symbols laid out as images/{train,val} + labels/{train,val}
    (see datasets/symbols.yaml and scripts/cubicasa_to_coco.py) — train()
    builds its own data.yaml from that layout, so nothing needs staging here.
    """
    import sys
    sys.path.insert(0, "/root/backend_training")
    sys.path.insert(0, "/root/training")
    import train as train_module  # app/training/train.py — only used here for upload_model_to_s3
    import train_yolov8_seg

    best_path = train_yolov8_seg.train(
        dataset_dir="/data/symbols", epochs=epochs, base_model=base_model, batch=batch,
        output_dir=Path("/models") / "symbol_counts",
    )

    if upload_to_s3:
        train_module.upload_model_to_s3(str(best_path), upload_to_s3)
    models_volume.commit()
    return str(best_path)


@app.function(
    image=training_image,
    gpu=None,  # lightweight CNN (train.py's WallClassifier) — CPU is enough, no need to rent a GPU
    volumes={"/data": datasets_volume, "/models": models_volume},
    secrets=[s3_secret],
    timeout=TRAIN_TIMEOUT_SECONDS,
)
def train_wall_classifier(epochs: int = 50, batch_size: int = 32, upload_to_s3: str = "") -> str:
    import sys
    sys.path.insert(0, "/root/training")
    import train as train_module

    best_path = train_module.train_wall_classifier(
        patch_dir="/data/wall_patches", epochs=epochs, batch_size=batch_size, device="cpu",
    )

    dest = Path("/models") / "wall_classifier_v1.pt"
    dest.write_bytes(Path(best_path).read_bytes())
    models_volume.commit()

    if upload_to_s3:
        train_module.upload_model_to_s3(str(dest), upload_to_s3)
    return str(dest)


@app.local_entrypoint()
def main(stage: str = "rooms", epochs: int = 0, model_size: str = "", base_model: str = "", batch: int = 0, upload_to_s3: str = ""):
    """
    Entry point for `modal run infra/modal_gpu.py --stage <rooms|symbols|walls> ...`.
    Deliberately NOT called by anything else in this file — a training run
    only starts when a human runs this command themselves.
    """
    if stage == "rooms":
        result = train_rooms.remote(
            **{k: v for k, v in {"epochs": epochs or None, "model_size": model_size or None, "batch": batch or None, "upload_to_s3": upload_to_s3}.items() if v}
        )
    elif stage == "symbols":
        result = train_symbols.remote(
            **{k: v for k, v in {"epochs": epochs or None, "base_model": base_model or None, "batch": batch or None, "upload_to_s3": upload_to_s3}.items() if v}
        )
    elif stage == "walls":
        result = train_wall_classifier.remote(
            **{k: v for k, v in {"epochs": epochs or None, "batch_size": batch or None, "upload_to_s3": upload_to_s3}.items() if v}
        )
    else:
        raise ValueError(f"Unknown stage: {stage!r} (expected rooms | symbols | walls)")

    print(f"[{stage}] training complete — weights at: {result}")
