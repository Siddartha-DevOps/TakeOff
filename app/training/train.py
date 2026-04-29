"""
TakeOff.ai — YOLOv8 Training Pipeline
Trains real blueprint detection models from scratch.

Quick start (local GPU):
    python training/train.py --stage 1 --dataset /path/to/data

Full pipeline:
    python training/train.py --stage all --dataset /path/to/data --device 0

Stages:
    1: YOLOv8m-seg  — rooms (segmentation) + doors/windows/MEP (detection)
    2: WallClassifier CNN — wall type classification
    3: Evaluate + export to ONNX for SageMaker deployment
"""

import argparse
import os
import json
import shutil
from pathlib import Path
import numpy as np
from loguru import logger


MODELS_DIR = Path(__file__).parent.parent / "models"
DATA_DIR = Path(__file__).parent.parent / "data"
RUNS_DIR = Path(__file__).parent.parent / "runs"


# ──────────────────────────────────────────────────────────────
# Stage 1: YOLOv8 Training
# ──────────────────────────────────────────────────────────────
def train_yolo(
    dataset_path: str,
    model_size: str = "m",           # n/s/m/l/x
    epochs: int = 200,
    imgsz: int = 1280,
    batch: int = 8,
    device: str = "0",
    resume: bool = False,
) -> Path:
    """
    Fine-tune YOLOv8-seg on blueprint dataset.

    Returns path to best.pt weights.
    """
    from ultralytics import YOLO

    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    base_model = f"yolov8{model_size}-seg.pt"
    logger.info(f"Training YOLOv8{model_size}-seg on {dataset_path}")
    logger.info(f"Epochs={epochs} | imgsz={imgsz} | batch={batch} | device={device}")

    model = YOLO(base_model)

    results = model.train(
        data=str(Path(dataset_path) / "data.yaml"),
        epochs=epochs,
        imgsz=imgsz,
        batch=batch,
        device=device,

        # Optimizer
        optimizer="AdamW",
        lr0=0.001,
        lrf=0.01,
        momentum=0.937,
        weight_decay=0.0005,
        warmup_epochs=3.0,

        # Augmentation
        # Blueprints are ALWAYS upright — NO rotation augmentation
        degrees=0,
        translate=0.1,
        scale=0.9,
        shear=0,
        perspective=0,
        flipud=0,           # no vertical flip (floor plans have up direction)
        fliplr=0.3,         # horizontal flip is valid (mirror image of a plan)
        mosaic=0.5,
        mixup=0.1,

        # Blueprint-specific: vary scan quality
        hsv_h=0.01,         # slight hue (color variation in scans)
        hsv_s=0.2,
        hsv_v=0.4,          # brightness (dark/light scans)

        # Training settings
        patience=50,        # early stopping
        save=True,
        save_period=10,
        project=str(RUNS_DIR),
        name="blueprint_seg",

        # Loss weights — tuned for blueprints
        # Higher box weight = more precise bounding boxes for small objects (doors)
        box=7.5,
        cls=0.5,
        dfl=1.5,

        # Performance
        workers=4,
        amp=True,           # mixed precision training
        cache=True,         # cache images in RAM/disk for faster epochs

        resume=resume,
        verbose=True,
    )

    # Copy best weights to models dir
    best_path = RUNS_DIR / "blueprint_seg" / "weights" / "best.pt"
    if best_path.exists():
        dest = MODELS_DIR / "rooms_doors_windows_v1.pt"
        shutil.copy(best_path, dest)
        logger.info(f"Best model saved to: {dest}")
        return dest

    logger.warning("best.pt not found — using last.pt")
    last_path = RUNS_DIR / "blueprint_seg" / "weights" / "last.pt"
    dest = MODELS_DIR / "rooms_doors_windows_v1_last.pt"
    shutil.copy(last_path, dest)
    return dest


# ──────────────────────────────────────────────────────────────
# Stage 2: Wall Classifier CNN
# ──────────────────────────────────────────────────────────────
def train_wall_classifier(
    patch_dir: str,      # dir with subfolders: exterior/, interior/, nonwall/
    epochs: int = 50,
    batch_size: int = 32,
    device: str = "cpu",
) -> Path:
    """
    Train a lightweight CNN to classify 32×32 line-segment patches as:
      0 = exterior wall
      1 = interior wall
      2 = non-wall line

    Target: >94% accuracy on 500 patches per class.
    """
    import torch
    import torch.nn as nn
    import torch.optim as optim
    from torch.utils.data import DataLoader, Dataset
    from torchvision import transforms
    import torchvision.datasets as datasets

    logger.info(f"Training WallClassifier on {patch_dir}")

    # Model definition (lightweight — runs in <1ms per patch)
    class WallClassifier(nn.Module):
        def __init__(self):
            super().__init__()
            self.features = nn.Sequential(
                nn.Conv2d(1, 32, 3, padding=1), nn.BatchNorm2d(32), nn.ReLU(),
                nn.Conv2d(32, 64, 3, padding=1), nn.BatchNorm2d(64), nn.ReLU(),
                nn.MaxPool2d(2),                             # 32→16
                nn.Conv2d(64, 128, 3, padding=1), nn.BatchNorm2d(128), nn.ReLU(),
                nn.AdaptiveAvgPool2d((4, 4)),
            )
            self.classifier = nn.Sequential(
                nn.Flatten(),
                nn.Linear(128 * 4 * 4, 256), nn.ReLU(),
                nn.Dropout(0.3),
                nn.Linear(256, 3),
            )

        def forward(self, x):
            return self.classifier(self.features(x))

    transform = transforms.Compose([
        transforms.Grayscale(),
        transforms.Resize((32, 32)),
        transforms.RandomHorizontalFlip(),
        transforms.RandomRotation(10),
        transforms.ToTensor(),
        transforms.Normalize([0.5], [0.5]),
    ])

    dataset = datasets.ImageFolder(patch_dir, transform=transform)
    n_val = max(1, int(len(dataset) * 0.2))
    n_train = len(dataset) - n_val
    train_ds, val_ds = torch.utils.data.random_split(dataset, [n_train, n_val])

    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=batch_size)

    model = WallClassifier().to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.AdamW(model.parameters(), lr=1e-3)
    scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

    best_acc = 0.0
    best_path = MODELS_DIR / "wall_classifier_v1.pt"

    for epoch in range(epochs):
        # Train
        model.train()
        train_loss = 0
        for imgs, labels in train_loader:
            imgs, labels = imgs.to(device), labels.to(device)
            optimizer.zero_grad()
            loss = criterion(model(imgs), labels)
            loss.backward()
            optimizer.step()
            train_loss += loss.item()

        # Validate
        model.eval()
        correct = total = 0
        with torch.no_grad():
            for imgs, labels in val_loader:
                imgs, labels = imgs.to(device), labels.to(device)
                preds = model(imgs).argmax(1)
                correct += (preds == labels).sum().item()
                total += labels.size(0)

        acc = correct / total if total > 0 else 0
        scheduler.step()

        if (epoch + 1) % 10 == 0:
            logger.info(f"Epoch {epoch+1}/{epochs} | loss={train_loss/len(train_loader):.4f} | val_acc={acc:.3f}")

        if acc > best_acc:
            best_acc = acc
            torch.save(model.state_dict(), str(best_path))

    logger.info(f"Wall classifier trained | best val_acc={best_acc:.3f} | saved: {best_path}")
    return best_path


# ──────────────────────────────────────────────────────────────
# Stage 3: Evaluate + Export
# ──────────────────────────────────────────────────────────────
def evaluate_model(model_path: str, data_yaml: str, device: str = "0") -> dict:
    """Run YOLO validation and return metrics."""
    from ultralytics import YOLO

    model = YOLO(str(model_path))
    metrics = model.val(data=data_yaml, device=device, verbose=True)

    results = {
        "mAP50": float(metrics.box.map50),
        "mAP50_95": float(metrics.box.map),
        "precision": float(metrics.box.p.mean()),
        "recall": float(metrics.box.r.mean()),
    }

    # Check targets (from AI_TRAINING_GUIDE.md)
    targets = {
        "mAP50": 0.85,
        "mAP50_95": 0.68,
        "precision": 0.80,
        "recall": 0.75,
    }

    logger.info("=== Evaluation Results ===")
    for metric, value in results.items():
        target = targets.get(metric, 0)
        status = "✅" if value >= target else "❌"
        logger.info(f"{status} {metric}: {value:.3f} (target: {target:.3f})")

    return results


def export_to_onnx(model_path: str) -> Path:
    """
    Export YOLO model to ONNX for SageMaker deployment.
    ONNX runs on any hardware without PyTorch dependency.
    """
    from ultralytics import YOLO

    model = YOLO(str(model_path))
    onnx_path = model.export(
        format="onnx",
        imgsz=1280,
        half=True,          # FP16 for faster inference on GPU
        dynamic=False,
        simplify=True,
        opset=17,
    )
    logger.info(f"ONNX model exported: {onnx_path}")
    return Path(onnx_path)


# ──────────────────────────────────────────────────────────────
# Dataset setup helpers
# ──────────────────────────────────────────────────────────────
def create_data_yaml(
    dataset_path: str,
    output_path: str | None = None,
) -> str:
    """
    Create the data.yaml config file for YOLO training.
    This tells YOLO where your train/val data is and what classes you have.
    """
    yaml_content = f"""# TakeOff.ai Blueprint Detection Dataset
path: {dataset_path}
train: train/images
val: val/images
test: test/images

# Total classes: 27
nc: 27
names:
  # Rooms (0-8) — segmentation masks
  0: living
  1: bedroom
  2: kitchen
  3: bathroom
  4: dining
  5: office
  6: hallway
  7: closet
  8: utility
  # Doors (9-13) — bounding boxes
  9: standard_door
  10: bifold_door
  11: sliding_door
  12: double_door
  13: pocket_door
  # Windows (14-18) — bounding boxes
  14: fixed_window
  15: casement_window
  16: sliding_window
  17: transom_window
  18: bay_window
  # MEP Plumbing (19-22)
  19: toilet
  20: sink
  21: shower
  22: bathtub
  # MEP Electrical (23-26)
  23: outlet
  24: switch
  25: light_fixture
  26: smoke_detector
"""
    out_path = output_path or str(Path(dataset_path) / "data.yaml")
    with open(out_path, "w") as f:
        f.write(yaml_content)
    logger.info(f"data.yaml written to: {out_path}")
    return out_path


def download_public_datasets(output_dir: str) -> None:
    """
    Download publicly available floor plan datasets for initial training.
    These are sufficient for MVP-level detection.

    Datasets:
      - RPLAN: 70K+ residential floor plans (HDF5 format)
      - CVC-FP: Segmented floor plan images
      - Structured3D: Synthetic floor plans

    Note: You still need to annotate doors/windows/MEP.
    RPLAN provides room segmentation annotations out of the box.
    """
    import urllib.request

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    datasets = {
        "rplan_sample": "https://github.com/ennauata/housegan/raw/master/data/sample.npy",
    }

    for name, url in datasets.items():
        dest = output_dir / f"{name}.npy"
        if not dest.exists():
            logger.info(f"Downloading {name}...")
            try:
                urllib.request.urlretrieve(url, str(dest))
                logger.info(f"Downloaded: {dest}")
            except Exception as e:
                logger.warning(f"Could not download {name}: {e}")
                logger.info("Manually download from: https://github.com/ennauata/housegan")


# ──────────────────────────────────────────────────────────────
# Upload trained model to S3
# ──────────────────────────────────────────────────────────────
def upload_model_to_s3(model_path: str, bucket: str, key_prefix: str = "models") -> str:
    """Upload trained weights to S3 for production deployment."""
    import boto3

    s3 = boto3.client("s3")
    filename = Path(model_path).name
    s3_key = f"{key_prefix}/{filename}"

    logger.info(f"Uploading {filename} to s3://{bucket}/{s3_key}")
    s3.upload_file(model_path, bucket, s3_key)
    s3_uri = f"s3://{bucket}/{s3_key}"
    logger.info(f"Uploaded: {s3_uri}")
    return s3_uri


# ──────────────────────────────────────────────────────────────
# CLI entry point
# ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TakeOff.ai Model Training")
    parser.add_argument("--stage", choices=["1", "2", "3", "all"], default="1",
                        help="Training stage: 1=YOLO, 2=WallCNN, 3=Eval/Export, all=all stages")
    parser.add_argument("--dataset", type=str, default=str(DATA_DIR / "blueprints"),
                        help="Path to annotated dataset directory")
    parser.add_argument("--model-size", type=str, default="m",
                        choices=["n", "s", "m", "l", "x"],
                        help="YOLO model size (n=nano, m=medium, x=extra large)")
    parser.add_argument("--epochs", type=int, default=200)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--device", type=str, default="auto",
                        help="Training device: 'cpu', '0' (GPU 0), 'auto'")
    parser.add_argument("--resume", action="store_true", help="Resume interrupted training")
    parser.add_argument("--upload-to-s3", type=str, default="",
                        help="S3 bucket name to upload trained model")
    parser.add_argument("--create-yaml", action="store_true",
                        help="Just create data.yaml and exit")

    args = parser.parse_args()

    if args.device == "auto":
        try:
            import torch
            args.device = "0" if torch.cuda.is_available() else "cpu"
        except ImportError:
            args.device = "cpu"

    logger.info(f"Using device: {args.device}")

    if args.create_yaml:
        create_data_yaml(args.dataset)
        exit(0)

    # Ensure data.yaml exists
    yaml_path = Path(args.dataset) / "data.yaml"
    if not yaml_path.exists():
        logger.info("data.yaml not found — creating...")
        create_data_yaml(args.dataset)

    model_path = None

    if args.stage in ("1", "all"):
        model_path = train_yolo(
            dataset_path=args.dataset,
            model_size=args.model_size,
            epochs=args.epochs,
            batch=args.batch,
            device=args.device,
            resume=args.resume,
        )

    if args.stage in ("2", "all"):
        patch_dir = Path(args.dataset) / "wall_patches"
        if patch_dir.exists():
            train_wall_classifier(str(patch_dir), device=args.device)
        else:
            logger.warning(f"Wall patch dir not found: {patch_dir} — skipping stage 2")

    if args.stage in ("3", "all"):
        mp = model_path or (MODELS_DIR / "rooms_doors_windows_v1.pt")
        if Path(str(mp)).exists():
            evaluate_model(str(mp), str(yaml_path), device=args.device)
            export_to_onnx(str(mp))
        else:
            logger.error(f"Model not found for evaluation: {mp}")

    if args.upload_to_s3 and model_path:
        upload_model_to_s3(str(model_path), args.upload_to_s3)

    logger.info("Training pipeline complete.")