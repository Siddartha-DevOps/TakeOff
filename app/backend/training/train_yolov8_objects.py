"""
Train a plain YOLOv8 (bounding-box detection, task="detect" — not -seg)
model for the Model 2 symbol/object classes (objects_dataset.SYMBOL_CLASSES),
built from SESYD + CubiCasa icon annotations (sesyd_to_yolo.py).

Runs on a GPU box (Colab/SageMaker/RunPod) or via modal_gpu_objects.py on
Modal — NOT inside a Vercel function or this repo's CI. Writes weights to
ai/models/object_detect/yolov8-objects.pt.

Usage
-----
    python training/train_yolov8_objects.py \
        --data datasets/symbols_yolo --epochs 300 --model yolov8m.pt
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from objects_dataset import build_objects_yaml  # noqa: E402

DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "ai" / "models" / "object_detect"


def train(
    dataset_dir: str,
    epochs: int = 300,
    imgsz: int = 1280,
    base_model: str = "yolov8m.pt",
    batch: int = 16,
    output_dir: Path = DEFAULT_OUTPUT,
) -> Path:
    """Fine-tune YOLOv8 detection and copy the best weights to the inference path."""
    from ultralytics import YOLO  # imported here so the module loads without it

    data_yaml = build_objects_yaml(Path(dataset_dir))

    model = YOLO(base_model)
    results = model.train(
        data=str(data_yaml),
        epochs=epochs,
        imgsz=imgsz,
        batch=batch,
        task="detect",
        project=str(output_dir / "runs"),
        name="object_detect",
        exist_ok=True,
        # Blueprint-specific: floor plans are always upright, symbols are small.
        degrees=0,
        flipud=0,
        fliplr=0.3,
        conf=0.2,
        box=10.0,
    )

    best = Path(results.save_dir) / "weights" / "best.pt"
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "yolov8-objects.pt"
    if best.exists():
        import shutil

        shutil.copy2(best, target)
        print(f"[train] weights -> {target}")
    else:
        print(f"[train] WARNING: best.pt not found at {best}")
    return target


def main() -> None:
    ap = argparse.ArgumentParser(description="Train YOLOv8 symbol/object detector")
    ap.add_argument("--data", required=True, help="Dataset dir (images/, labels/)")
    ap.add_argument("--epochs", type=int, default=300)
    ap.add_argument("--imgsz", type=int, default=1280)
    ap.add_argument("--model", default="yolov8m.pt", help="Base weights to fine-tune")
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = ap.parse_args()

    train(
        dataset_dir=args.data,
        epochs=args.epochs,
        imgsz=args.imgsz,
        base_model=args.model,
        batch=args.batch,
        output_dir=Path(args.output),
    )


if __name__ == "__main__":
    main()
