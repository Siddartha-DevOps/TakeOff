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
import numpy as np
from pathlib import Path
from typing import Optional
from loguru import logger

# NOTE: Heavy / optional dependencies (boto3, cv2, ultralytics, torch) and the
# sibling preprocessing/scale_detection modules are imported lazily inside the
# functions that need them. This keeps `import detection_engine` cheap on web
# workers (which only need model_is_available()) and lets the module be imported
# even when the full AI stack is not installed.

# Default DPI for unit conversion (mirrors preprocessing.TARGET_DPI). Defined
# locally so the module can be imported without pulling in OpenCV/PyMuPDF.
DEFAULT_DPI = 300


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
def _ensure_model(model_filename: str) -> Optional[Path]:
    """
    Ensure model weights are available locally.
    Downloads from S3 if not present and S3_BUCKET is configured.

    Returns the local path to the weights, or None if no trained model is
    available. Callers are expected to handle the None case gracefully
    (e.g. fall back to an "untrained" result) rather than crashing — the app
    must stay responsive before training is complete.
    """
    local_path = MODELS_DIR / model_filename
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    if local_path.exists():
        return local_path

    if S3_BUCKET:
        import boto3  # lazy: only needed when pulling weights from S3

        logger.info(f"Downloading model {model_filename} from S3...")
        s3 = boto3.client("s3")
        s3_key = f"models/{model_filename}"
        try:
            s3.download_file(S3_BUCKET, s3_key, str(local_path))
            logger.info(f"Model downloaded: {local_path}")
            return local_path
        except Exception as e:
            logger.error(f"S3 download failed: {e}")

    logger.warning(
        f"Model not found: {local_path}. "
        f"Train first (python training/train.py) or set AI_MODELS_BUCKET to "
        f"auto-download from S3. Detection will return an empty 'untrained' result."
    )
    return None


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

        Never raises on missing weights or a missing ultralytics install.
        Check `self.available` (or just call detect(), which returns an empty
        "untrained" result) to know whether real inference will run.
        """
        self.model_filename = model_filename
        self.model = None
        self.available = False

        model_path = _ensure_model(model_filename)
        if model_path is None:
            return  # untrained — detect() returns an empty result

        try:
            from ultralytics import YOLO
        except ImportError:
            logger.warning(
                "ultralytics not installed — detection disabled. "
                "Run: pip install ultralytics"
            )
            return

        self._device = self._resolve_device(device)
        logger.info(f"Loading model on device: {self._device}")
        self.model = YOLO(str(model_path))
        self.available = True
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
        dpi: int = DEFAULT_DPI,
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
            If no trained model is loaded, returns an empty "untrained" result
            with the same shape instead of raising.
        """
        t_start = time.time()
        scale_ratio = scale_info["ratio"] if scale_info else 96.0

        if self.model is None:
            return _empty_result(scale_ratio, t_start)

        # Lazy import — keeps the module importable without the full AI stack.
        from preprocessing import preprocess_for_yolo, pixels_to_feet, pixels_to_sqft

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


def _empty_result(scale_ratio: float, t_start: float) -> dict:
    """
    Return an empty detection result with the same schema as a real detection,
    flagged as 'untrained'. Used when no model weights are available so the
    pipeline completes cleanly (status COMPLETED) instead of crashing or
    leaving the drawing stuck in PROCESSING.
    """
    return {
        "rooms": [],
        "doors": [],
        "windows": [],
        "mep": [],
        "summary": {
            "rooms": 0,
            "doors": 0,
            "windows": 0,
            "mep": 0,
            "walls": 0,
            "totalArea": 0,
        },
        "quantities": [],
        "scale_ratio": scale_ratio,
        "processing_time_ms": int((time.time() - t_start) * 1000),
        "model_version": "untrained",
        "model_status": "untrained",
        "message": (
            "AI model not trained yet. Run: python training/train.py "
            "or set AI_MODELS_BUCKET to download trained weights from S3."
        ),
    }


def model_is_available(model_filename: str = "rooms_doors_windows_v1.pt") -> bool:
    """Check whether a trained model exists locally or on S3."""
    local_path = MODELS_DIR / model_filename
    if local_path.exists():
        return True
    if S3_BUCKET:
        try:
            import boto3  # lazy: only needed when an S3 bucket is configured

            s3 = boto3.client("s3")
            s3.head_object(Bucket=S3_BUCKET, Key=f"models/{model_filename}")
            return True
        except Exception:
            pass
    return False