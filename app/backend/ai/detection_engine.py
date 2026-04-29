"""
TakeOff.ai — Real AI Detection Engine
Replaces ALL mock detection in mockAI.js and the mock Python pipeline.

Models:
  - YOLOv8m-seg : room segmentation + door/window/MEP detection
  - WallClassifier CNN : wall type classification (built-in lightweight CNN)

Works locally (CPU/GPU) and on AWS SageMaker without code changes.
Model weights are loaded from:
  - Local: ./models/{model_name}.pt
  - S3: s3://{BUCKET}/models/{model_name}.pt (auto-downloaded on first run)
"""

import os
import json
import uuid
import time
import boto3
import numpy as np
import cv2
from pathlib import Path
from typing import Optional
from loguru import logger

from preprocessing import (
    preprocess_for_yolo,
    pixels_to_feet,
    pixels_to_sqft,
    TARGET_DPI,
)
from scale_detection import run_ocr_for_scale


# ──────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────
MODELS_DIR = Path(__file__).parent / "models"
S3_BUCKET = os.getenv("AI_MODELS_BUCKET", "")     # e.g. "takeoffai-models"
CONFIDENCE_THRESHOLD = 0.25                         # minimum detection confidence
IOU_THRESHOLD = 0.45                                # NMS IoU threshold

# Detection class IDs (must match training data.yaml)
CLASS_NAMES = {
    # Rooms (segmentation)
    0:  "living",
    1:  "bedroom",
    2:  "kitchen",
    3:  "bathroom",
    4:  "dining",
    5:  "office",
    6:  "hallway",
    7:  "closet",
    8:  "utility",
    # Doors
    9:  "standard_door",
    10: "bifold_door",
    11: "sliding_door",
    12: "double_door",
    13: "pocket_door",
    # Windows
    14: "fixed_window",
    15: "casement_window",
    16: "sliding_window",
    17: "transom_window",
    18: "bay_window",
    # MEP
    19: "toilet",
    20: "sink",
    21: "shower",
    22: "bathtub",
    23: "outlet",
    24: "switch",
    25: "light_fixture",
    26: "smoke_detector",
}

ROOM_CLASSES = set(range(0, 9))
DOOR_CLASSES = set(range(9, 14))
WINDOW_CLASSES = set(range(14, 19))
MEP_CLASSES = set(range(19, 27))

# Room colors for frontend (matches existing mockAI.js colors)
ROOM_COLORS = {
    "living":     "#818cf8",
    "bedroom":    "#c4b5fd",
    "kitchen":    "#fbbf24",
    "bathroom":   "#22d3ee",
    "dining":     "#f472b6",
    "office":     "#34d399",
    "hallway":    "#94a3b8",
    "closet":     "#cbd5e1",
    "utility":    "#fb7185",
}


# ──────────────────────────────────────────────────────────────
# Model loading with S3 auto-download
# ──────────────────────────────────────────────────────────────
def _ensure_model(model_filename: str) -> Path:
    """
    Ensure model weights are available locally.
    Downloads from S3 if not present and S3_BUCKET is configured.
    """
    local_path = MODELS_DIR / model_filename
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    if local_path.exists():
        return local_path

    if S3_BUCKET:
        logger.info(f"Downloading model {model_filename} from S3...")
        s3 = boto3.client("s3")
        s3_key = f"models/{model_filename}"
        try:
            s3.download_file(S3_BUCKET, s3_key, str(local_path))
            logger.info(f"Model downloaded: {local_path}")
            return local_path
        except Exception as e:
            logger.error(f"S3 download failed: {e}")

    # No model found — caller must handle training first
    raise FileNotFoundError(
        f"Model not found: {local_path}\n"
        f"Train first: python training/train.py\n"
        f"Or set AI_MODELS_BUCKET env var to download from S3."
    )


class BlueprintDetector:
    """
    Main AI detection engine. Initialize once; call detect() per drawing.
    Thread-safe (inference only, no state mutation).
    """

    def __init__(
        self,
        model_filename: str = "rooms_doors_windows_v1.pt",
        device: str = "auto",
    ):
        """
        Args:
            model_filename: Name of the YOLO .pt weights file.
            device: 'auto' | 'cpu' | '0' (GPU index) | 'cuda'
        """
        try:
            from ultralytics import YOLO
        except ImportError:
            raise ImportError("ultralytics not installed. Run: pip install ultralytics")

        self._device = self._resolve_device(device)
        logger.info(f"Loading model on device: {self._device}")

        model_path = _ensure_model(model_filename)
        self.model = YOLO(str(model_path))
        logger.info(f"Model loaded: {model_filename}")

    @staticmethod
    def _resolve_device(device: str) -> str:
        if device != "auto":
            return device
        try:
            import torch
            return "0" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"

    # ──────────────────────────────────────────
    # Main detection method
    # ──────────────────────────────────────────
    def detect(
        self,
        img: np.ndarray,
        scale_info: Optional[dict] = None,
        dpi: int = TARGET_DPI,
    ) -> dict:
        """
        Run full detection on a preprocessed blueprint image.

        Args:
            img:        BGR numpy array from preprocessing.load_drawing()
            scale_info: Output from scale_detection.run_ocr_for_scale()
            dpi:        Image DPI for unit conversion

        Returns:
            Detection dict matching the schema expected by the frontend
            (same structure as SAMPLE_DETECTION in mockAI.js, but real data).
        """
        t_start = time.time()
        scale_ratio = scale_info["ratio"] if scale_info else 96.0

        # Preprocess
        processed = preprocess_for_yolo(img)

        # Run YOLO inference
        results = self.model.predict(
            source=processed,
            imgsz=1280,
            conf=CONFIDENCE_THRESHOLD,
            iou=IOU_THRESHOLD,
            device=self._device,
            verbose=False,
        )

        # Parse detections
        rooms = []
        doors = []
        windows = []
        mep = []

        if results and len(results) > 0:
            result = results[0]
            boxes = result.boxes
            masks = result.masks  # None if no segmentation model

            for i, box in enumerate(boxes):
                cls_id = int(box.cls[0].item())
                conf = float(box.conf[0].item())
                x1, y1, x2, y2 = [float(v) for v in box.xyxy[0].tolist()]

                det_id = str(uuid.uuid4())[:8]

                if cls_id in ROOM_CLASSES:
                    label = CLASS_NAMES[cls_id].replace("_", " ").title()
                    pixel_area = (x2 - x1) * (y2 - y1)

                    # Use segmentation mask area if available (more accurate)
                    if masks is not None and i < len(masks.data):
                        mask_np = masks.data[i].cpu().numpy()
                        pixel_area = float(np.sum(mask_np > 0.5))

                    area_sqft = round(pixels_to_sqft(pixel_area, scale_ratio, dpi), 0)

                    rooms.append({
                        "id": f"r_{det_id}",
                        "label": label,
                        "bbox": [round(x1), round(y1), round(x2), round(y2)],
                        "area": int(area_sqft),
                        "confidence": round(conf, 3),
                        "color": ROOM_COLORS.get(CLASS_NAMES[cls_id], "#818cf8"),
                        "class_id": cls_id,
                    })

                elif cls_id in DOOR_CLASSES:
                    center_x = (x1 + x2) / 2
                    center_y = (y1 + y2) / 2
                    width_px = x2 - x1
                    height_px = y2 - y1
                    door_type = CLASS_NAMES[cls_id]

                    # Determine swing direction from aspect ratio
                    rotation = 90 if height_px > width_px else 0

                    # Estimate door width in inches from pixel size
                    door_width_inches = round(
                        pixels_to_feet(max(width_px, height_px), scale_ratio, dpi) * 12
                    )
                    # Snap to standard widths: 24", 28", 30", 32", 36"
                    door_width_inches = _snap_to_standard_width(door_width_inches)

                    doors.append({
                        "id": f"d_{det_id}",
                        "type": door_type,
                        "x": round(center_x),
                        "y": round(center_y),
                        "bbox": [round(x1), round(y1), round(x2), round(y2)],
                        "width": door_width_inches,
                        "rotation": rotation,
                        "confidence": round(conf, 3),
                    })

                elif cls_id in WINDOW_CLASSES:
                    width_px = x2 - x1
                    height_px = y2 - y1
                    is_horizontal = width_px >= height_px

                    window_width_inches = round(
                        pixels_to_feet(max(width_px, height_px), scale_ratio, dpi) * 12
                    )

                    windows.append({
                        "id": f"w_{det_id}",
                        "type": CLASS_NAMES[cls_id],
                        "x": round(x1),
                        "y": round((y1 + y2) / 2),
                        "bbox": [round(x1), round(y1), round(x2), round(y2)],
                        "width": max(window_width_inches, 12),  # min 12" window
                        "rotation": 0 if is_horizontal else 90,
                        "confidence": round(conf, 3),
                    })

                elif cls_id in MEP_CLASSES:
                    mep.append({
                        "id": f"m_{det_id}",
                        "type": CLASS_NAMES[cls_id],
                        "x": round((x1 + x2) / 2),
                        "y": round((y1 + y2) / 2),
                        "bbox": [round(x1), round(y1), round(x2), round(y2)],
                        "confidence": round(conf, 3),
                    })

        # Compute summary + quantities
        quantities = compute_quantities(rooms, doors, windows, mep, scale_ratio, dpi)
        summary = {
            "rooms": len(rooms),
            "doors": len(doors),
            "windows": len(windows),
            "mep": len(mep),
            "walls": 0,  # computed separately by wall detector
            "totalArea": sum(r["area"] for r in rooms),
        }

        elapsed_ms = int((time.time() - t_start) * 1000)
        logger.info(
            f"Detection complete: {len(rooms)} rooms, {len(doors)} doors, "
            f"{len(windows)} windows, {len(mep)} MEP | {elapsed_ms}ms"
        )

        return {
            "rooms": rooms,
            "doors": doors,
            "windows": windows,
            "mep": mep,
            "summary": summary,
            "quantities": quantities,
            "scale_ratio": scale_ratio,
            "processing_time_ms": elapsed_ms,
            "model_version": "yolov8m-seg-v1",
        }


# ──────────────────────────────────────────────────────────────
# Quantity calculation from detections
# ──────────────────────────────────────────────────────────────
def compute_quantities(
    rooms: list[dict],
    doors: list[dict],
    windows: list[dict],
    mep: list[dict],
    scale_ratio: float,
    dpi: int,
) -> list[dict]:
    """
    Compute trade quantities from detection results.
    Returns list of {trade, item, quantity, unit} dicts
    matching the schema expected by the frontend QuantitiesPanel.
    """
    quantities = []

    total_area = sum(r["area"] for r in rooms)
    wet_area = sum(
        r["area"] for r in rooms
        if r["label"].lower() in ("bathroom", "kitchen", "utility", "laundry")
    )
    dry_area = total_area - wet_area
    bedroom_area = sum(
        r["area"] for r in rooms
        if "bedroom" in r["label"].lower() or "closet" in r["label"].lower()
    )

    # Estimate wall linear footage: perimeter of all rooms + interior partitions
    # Rough formula: total_perimeter ≈ 4 * sqrt(total_area) * 1.8 (factor for complexity)
    wall_lf = round(4 * (total_area ** 0.5) * 1.8) if total_area > 0 else 0

    # Drywall
    wall_height_ft = 9  # assume 9' ceiling
    wall_sf = wall_lf * wall_height_ft * 2  # both sides
    if wall_lf > 0:
        quantities += [
            {"trade": "Drywall", "item": "Interior partition linear feet", "quantity": wall_lf, "unit": "lf"},
            {"trade": "Drywall", "item": "Gypsum board surface area", "quantity": wall_sf, "unit": "sf"},
        ]

    # Painting
    ceiling_sf = total_area
    paint_wall_sf = wall_sf
    if total_area > 0:
        quantities += [
            {"trade": "Painting", "item": "Paintable wall area", "quantity": round(paint_wall_sf * 0.85), "unit": "sf"},
            {"trade": "Painting", "item": "Ceiling paintable area", "quantity": ceiling_sf, "unit": "sf"},
        ]

    # Flooring
    if bedroom_area > 0:
        quantities.append({"trade": "Flooring", "item": "Carpet — bedrooms/closets", "quantity": bedroom_area, "unit": "sf"})
    if wet_area > 0:
        quantities.append({"trade": "Flooring", "item": "Tile — wet areas", "quantity": wet_area, "unit": "sf"})
    common_area = max(0, dry_area - bedroom_area)
    if common_area > 0:
        quantities.append({"trade": "Flooring", "item": "Hardwood/LVP — common areas", "quantity": common_area, "unit": "sf"})

    # Doors
    if doors:
        std_doors = [d for d in doors if d["type"] in ("standard_door", "pocket_door")]
        bifold_doors = [d for d in doors if d["type"] == "bifold_door"]
        dbl_doors = [d for d in doors if d["type"] == "double_door"]

        if std_doors:
            quantities.append({"trade": "Doors", "item": "Interior doors 3'-0\"", "quantity": len(std_doors), "unit": "ea"})
        if bifold_doors:
            quantities.append({"trade": "Doors", "item": "Bi-fold doors", "quantity": len(bifold_doors), "unit": "ea"})
        if dbl_doors:
            quantities.append({"trade": "Doors", "item": "Double doors", "quantity": len(dbl_doors), "unit": "ea"})

    # Windows
    if windows:
        sliding = [w for w in windows if "sliding" in w["type"]]
        fixed = [w for w in windows if "fixed" in w["type"]]
        casement = [w for w in windows if "casement" in w["type"]]
        transom = [w for w in windows if "transom" in w["type"]]
        other_w = [w for w in windows if w not in sliding + fixed + casement + transom]

        for label, wlist in [
            ("Double-hung/sliding windows", sliding),
            ("Fixed windows", fixed),
            ("Casement windows", casement),
            ("Transom windows", transom),
            ("Other windows", other_w),
        ]:
            if wlist:
                quantities.append({"trade": "Windows", "item": label, "quantity": len(wlist), "unit": "ea"})

    # Electrical (from MEP)
    outlets = [m for m in mep if m["type"] == "outlet"]
    switches = [m for m in mep if m["type"] == "switch"]
    fixtures = [m for m in mep if m["type"] == "light_fixture"]
    smoke = [m for m in mep if m["type"] == "smoke_detector"]

    if outlets:
        quantities.append({"trade": "Electrical", "item": "Standard duplex outlets", "quantity": len(outlets), "unit": "ea"})
    if switches:
        quantities.append({"trade": "Electrical", "item": "Light switches", "quantity": len(switches), "unit": "ea"})
    if fixtures:
        quantities.append({"trade": "Electrical", "item": "Light fixtures", "quantity": len(fixtures), "unit": "ea"})
    if smoke:
        quantities.append({"trade": "Electrical", "item": "Smoke detectors", "quantity": len(smoke), "unit": "ea"})

    # Plumbing
    plumbing_types = {"toilet": "Toilets", "sink": "Sinks", "shower": "Showers/tubs", "bathtub": "Bathtubs"}
    for mtype, label in plumbing_types.items():
        items = [m for m in mep if m["type"] == mtype]
        if items:
            quantities.append({"trade": "Plumbing", "item": label, "quantity": len(items), "unit": "ea"})

    return quantities


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────
def _snap_to_standard_width(inches: int) -> int:
    """Snap detected door width to nearest standard size."""
    standards = [24, 28, 30, 32, 36, 42, 48, 60, 72]
    return min(standards, key=lambda s: abs(s - inches))


def model_is_available(model_filename: str = "rooms_doors_windows_v1.pt") -> bool:
    """Check whether a trained model exists locally or on S3."""
    local_path = MODELS_DIR / model_filename
    if local_path.exists():
        return True
    if S3_BUCKET:
        try:
            s3 = boto3.client("s3")
            s3.head_object(Bucket=S3_BUCKET, Key=f"models/{model_filename}")
            return True
        except Exception:
            pass
    return False