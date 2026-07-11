"""
Raster symbol detection — YOLOv8-seg inference for scanned/raster sheets.

The vector path (`geometry.vector_symbol_match`) handles vector PDFs with no
model. Scanned sheets have no vector primitives, so they need a trained
segmentation model. This module is the *inference* half: it rasterizes the page,
runs YOLOv8-seg, and summarizes detections into per-type counts.

It never raises on missing weights — it returns a ``needs_weights`` result so the
API degrades gracefully until `training/train_yolov8_seg.py` produces
``models/symbol_counts/yolov8-seg.pt``.

Deliberately free of FastAPI/heavy imports at module load: ``summarize_counts``
is pure and unit-testable, and ultralytics/torch are imported lazily.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Optional

# Trained symbol weights live here (produced off-box by the training script).
SYMBOL_MODEL_DIR = Path(__file__).parent / "models" / "symbol_counts"
SYMBOL_MODEL_PATH = SYMBOL_MODEL_DIR / "yolov8-seg.pt"

# Class map for the symbol model. Doors / windows / MEP fixtures — the object
# types Togal counts. Mirrors the countable subset of detection_engine.CLASS_NAMES.
SYMBOL_CLASS_NAMES: dict[int, str] = {
    0: "standard_door",
    1: "bifold_door",
    2: "sliding_door",
    3: "double_door",
    4: "pocket_door",
    5: "fixed_window",
    6: "casement_window",
    7: "sliding_window",
    8: "transom_window",
    9: "bay_window",
    10: "toilet",
    11: "sink",
    12: "shower",
    13: "bathtub",
    14: "outlet",
    15: "switch",
    16: "light_fixture",
    17: "smoke_detector",
}


def summarize_counts(
    class_ids: list[int],
    class_names: Optional[dict[int, str]] = None,
) -> dict[str, int]:
    """Reduce a list of detected class ids to per-type counts.

    Pure and dependency-free so it is unit-testable without a model. Unknown ids
    fall back to a ``class_<id>`` label rather than being dropped.
    """
    names = class_names or SYMBOL_CLASS_NAMES
    counts: Counter[str] = Counter()
    for cid in class_ids:
        counts[names.get(int(cid), f"class_{int(cid)}")] += 1
    return dict(counts)


def symbol_weights_available() -> bool:
    """True if trained symbol weights are present locally."""
    return SYMBOL_MODEL_PATH.exists()


def detect_symbols_raster(
    file_path: str | Path,
    page_no: int = 0,
    conf: float = 0.25,
) -> dict[str, Any]:
    """Run YOLOv8-seg symbol detection on a rasterized page.

    Returns per-type counts + per-instance bbox/confidence, or a
    ``status="needs_weights"`` result when no trained model is installed.
    """
    if not symbol_weights_available():
        return {
            "method": "ai",
            "status": "needs_weights",
            "symbol_counts": {},
            "total_symbols": 0,
            "message": (
                "No trained symbol weights at "
                f"{SYMBOL_MODEL_PATH.relative_to(Path(__file__).parent.parent)}. "
                "Train with training/train_yolov8_seg.py or supply weights."
            ),
        }

    try:
        from ultralytics import YOLO
    except ImportError:
        return {
            "method": "ai",
            "status": "needs_weights",
            "symbol_counts": {},
            "total_symbols": 0,
            "message": "ultralytics not installed — run: pip install ultralytics",
        }

    from preprocessing import load_drawing, preprocess_for_yolo

    img = load_drawing(file_path, page_number=page_no)
    processed = preprocess_for_yolo(img)

    model = YOLO(str(SYMBOL_MODEL_PATH))
    results = model.predict(source=processed, imgsz=1280, conf=conf, verbose=False)

    class_ids: list[int] = []
    instances: list[dict[str, Any]] = []
    if results:
        boxes = results[0].boxes
        for box in boxes:
            cid = int(box.cls[0].item())
            class_ids.append(cid)
            x1, y1, x2, y2 = (float(v) for v in box.xyxy[0].tolist())
            instances.append(
                {
                    "symbol_type": SYMBOL_CLASS_NAMES.get(cid, f"class_{cid}"),
                    "bbox": [round(x1), round(y1), round(x2), round(y2)],
                    "confidence": round(float(box.conf[0].item()), 3),
                }
            )

    counts = summarize_counts(class_ids)
    return {
        "method": "ai",
        "status": "ok",
        "symbol_counts": counts,
        "total_symbols": int(sum(counts.values())),
        "instances": instances,
    }
