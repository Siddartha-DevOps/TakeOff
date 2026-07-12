"""
Train a YOLOv8-seg model to detect + count architectural symbols on RASTER
sheets (doors, windows, plumbing/electrical fixtures) — the ~18 object types
Togal counts.

This is the RASTER fallback. Vector PDFs are counted geometrically with no model
(see geometry/vector_symbol_match.py); this model covers scanned / image sheets.

Runs on a GPU box (Colab / SageMaker / RunPod), NOT inside a Vercel function or
this repo's CI. It writes weights to ai/models/symbol_counts/yolov8-seg.pt, which
ai/detect_symbols.py loads for inference.

Dataset
-------
Ultralytics segmentation layout, one .txt per image with polygon masks:

    dataset/
      images/{train,val}/*.png      # rasterized plan crops @ ~300 DPI
      labels/{train,val}/*.txt      # class_id x1 y1 x2 y2 ... (normalized polygon)
    data.yaml                       # written by build_data_yaml()

Source data: annotate real plans in CVAT/Label Studio, and/or bootstrap from
public floor-plan datasets (CubiCasa5K, RPLAN, Structured3D) remapped to the
class list below.

Usage
-----
    python training/train_yolov8_seg.py \
        --data /path/dataset --epochs 100 --imgsz 1280 --model yolov8m-seg.pt
"""

from __future__ import annotations

import argparse
from pathlib import Path

# Keep in lock-step with ai/detect_symbols.SYMBOL_CLASS_NAMES.
SYMBOL_CLASSES = [
    "standard_door", "bifold_door", "sliding_door", "double_door", "pocket_door",
    "fixed_window", "casement_window", "sliding_window", "transom_window", "bay_window",
    "toilet", "sink", "shower", "bathtub",
    "outlet", "switch", "light_fixture", "smoke_detector",
]

DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "ai" / "models" / "symbol_counts"


def build_data_yaml(dataset_dir: Path) -> Path:
    """Write the Ultralytics data.yaml for the symbol classes."""
    dataset_dir = Path(dataset_dir)
    names = "\n".join(f"  {i}: {name}" for i, name in enumerate(SYMBOL_CLASSES))
    yaml_text = (
        f"path: {dataset_dir}\n"
        f"train: images/train\n"
        f"val: images/val\n"
        f"nc: {len(SYMBOL_CLASSES)}\n"
        f"names:\n{names}\n"
    )
    out = dataset_dir / "data.yaml"
    out.write_text(yaml_text)
    return out


def train(
    dataset_dir: str,
    epochs: int = 100,
    imgsz: int = 1280,
    base_model: str = "yolov8m-seg.pt",
    batch: int = 8,
    output_dir: Path = DEFAULT_OUTPUT,
) -> Path:
    """Fine-tune YOLOv8-seg and copy the best weights to the inference path."""
    from ultralytics import YOLO  # imported here so the module loads without it

    data_yaml = build_data_yaml(Path(dataset_dir))

    model = YOLO(base_model)
    results = model.train(
        data=str(data_yaml),
        epochs=epochs,
        imgsz=imgsz,
        batch=batch,
        task="segment",
        project=str(output_dir / "runs"),
        name="symbol_counts",
        exist_ok=True,
    )

    # Copy best.pt to the stable path detect_symbols.py loads.
    best = Path(results.save_dir) / "weights" / "best.pt"
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "yolov8-seg.pt"
    if best.exists():
        import shutil

        shutil.copy2(best, target)
        print(f"[train] weights -> {target}")
    else:
        print(f"[train] WARNING: best.pt not found at {best}")
    return target


def main() -> None:
    ap = argparse.ArgumentParser(description="Train YOLOv8-seg symbol detector")
    ap.add_argument("--data", required=True, help="Dataset dir (images/, labels/)")
    ap.add_argument("--epochs", type=int, default=100)
    ap.add_argument("--imgsz", type=int, default=1280)
    ap.add_argument("--model", default="yolov8m-seg.pt", help="Base weights to fine-tune")
    ap.add_argument("--batch", type=int, default=8)
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
