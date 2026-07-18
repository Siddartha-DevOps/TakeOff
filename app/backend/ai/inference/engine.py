"""
Production inference engine — device-aware, multi-model, tiled.

Replaces ``TakeoffAIInference._mock_analysis``. When no trained model is present,
``analyze`` raises ``ModelUnavailableError`` (no fabricated detections); the
caller degrades to the real vector-PDF path or marks the job failed.

The detection-partitioning and quantity logic are pure module-level functions
(unit-tested); ultralytics / torch / cv2 are imported lazily inside ``_infer``
and ``_load_model`` so this module imports on a plain CI box.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from .device import DeviceInfo, resolve_device
from .tiling import run_tiled

# Space + symbol class map (unchanged ids — matches training data.yaml and the
# old inference_api.CLASSES so persisted results stay compatible).
CLASSES = {
    0: "living",    1: "bedroom",  2: "bathroom",
    3: "kitchen",   4: "wall",     5: "door",
    6: "window",    7: "balcony",  8: "front_door",
    9: "stair",     10: "storage",
}

# A page wider/taller than this (px) is tiled by default (large-drawing path).
DEFAULT_TILE_THRESHOLD = 2000


class ModelUnavailableError(RuntimeError):
    """Raised when inference is requested but no trained model is installed."""


@dataclass
class ModelSpec:
    """One registered model in the multi-model registry."""
    task: str                 # 'spaces' | 'symbols' | future trades
    name: str                 # version tag, e.g. 'yolov8m-seg-v1.0'
    weights_path: str
    class_map: dict = field(default_factory=lambda: dict(CLASSES))
    conf: float = 0.35
    iou: float = 0.45


@dataclass
class TakeoffAnalysis:
    """Backward-compatible result shape (new fields default so old callers work)."""
    drawing_id: int
    processing_time_ms: int
    ai_model_version: str
    rooms: list
    doors: list
    windows: list
    walls: list
    balconies: list
    summary: dict
    quantities: list
    confidence_avg: float
    model_available: bool = True
    status: str = "ok"
    device: str = "cpu"


# --------------------------------------------------------------------------- #
# Pure logic (unit-tested, no torch)
# --------------------------------------------------------------------------- #
def partition_detections(detections):
    """Split normalized detection dicts into rooms/doors/windows/walls/balconies.

    Each detection: ``{"label", "bbox", "confidence", "area", "polygon"?}``.
    Returns (rooms, doors, windows, walls, balconies, summary, confidence_avg).
    """
    rooms, doors, windows, walls, balconies = [], [], [], [], []
    confs = []
    for d in detections:
        name = d.get("label", "unknown")
        if d.get("confidence") is not None:
            confs.append(float(d["confidence"]))
        if name == "door":
            doors.append(d)
        elif name == "window":
            windows.append(d)
        elif name == "wall":
            walls.append(d)
        elif name == "balcony":
            balconies.append(d)
        else:
            rooms.append(d)
    summary = {
        "rooms": len(rooms), "doors": len(doors),
        "windows": len(windows), "walls": len(walls),
        "totalArea": round(sum((r.get("area") or 0) for r in rooms), 1),
    }
    avg = round(float(np.mean(confs)), 3) if confs else 0.0
    return rooms, doors, windows, walls, balconies, summary, avg


def raster_quantities(rooms, doors, windows, walls):
    """Rule-of-thumb trade quantities from raster detections (unchanged logic).

    NOTE: precise, scale-calibrated quantities come from ``geometry/`` on real
    PostGIS geometry; this is the quick summary tied to the detection blob.
    """
    flooring = {"bedroom": "Carpet", "bathroom": "Tile", "kitchen": "Tile"}
    by_mat: dict = {}
    for r in rooms:
        mat = flooring.get(r.get("label"), "Hardwood")
        by_mat[mat] = by_mat.get(mat, 0) + (r.get("area") or 0)
    qs = [{"trade": "Flooring", "item": f"{mat} flooring", "quantity": round(a, 1), "unit": "sf"}
          for mat, a in by_mat.items()]
    total_lf = sum(max(w["bbox"][2] - w["bbox"][0], w["bbox"][3] - w["bbox"][1]) for w in walls if w.get("bbox"))
    qs += [
        {"trade": "Drywall",    "item": "Wall linear footage", "quantity": round(total_lf / 9, 1), "unit": "lf"},
        {"trade": "Drywall",    "item": "Gypsum board (9ft)",  "quantity": round(total_lf, 1),     "unit": "sf"},
        {"trade": "Doors",      "item": "Interior doors",      "quantity": len(doors),             "unit": "ea"},
        {"trade": "Windows",    "item": "Window openings",     "quantity": len(windows),           "unit": "ea"},
        {"trade": "Electrical", "item": "Outlets (est.)",      "quantity": max(1, len(rooms) * 5), "unit": "ea"},
        {"trade": "Plumbing",   "item": "Fixtures (est.)",
         "quantity": sum(3 if r.get("label") == "bathroom" else 1
                         for r in rooms if r.get("label") in ("bathroom", "kitchen")), "unit": "ea"},
    ]
    return qs


# --------------------------------------------------------------------------- #
# Multi-model registry
# --------------------------------------------------------------------------- #
class ModelRegistry:
    """Task → ModelSpec registry with lazy, cached model loading (item: multi-model)."""

    def __init__(self, device: str = "auto"):
        self.device_info: DeviceInfo = resolve_device(device)
        self._specs: dict = {}
        self._loaded: dict = {}

    def register(self, spec: ModelSpec) -> None:
        self._specs[spec.task] = spec

    def spec(self, task: str) -> Optional[ModelSpec]:
        return self._specs.get(task)

    def available(self, task: str) -> bool:
        spec = self._specs.get(task)
        return bool(spec and os.path.exists(spec.weights_path))

    def load(self, task: str):
        """Lazily load + cache the ultralytics model for a task (GPU box only)."""
        if task in self._loaded:
            return self._loaded[task]
        spec = self._specs.get(task)
        if not spec or not os.path.exists(spec.weights_path):
            raise ModelUnavailableError(f"No weights for task {task!r}")
        from ultralytics import YOLO  # lazy
        model = YOLO(spec.weights_path)
        try:
            model.to(self.device_info.device)
        except Exception:
            pass  # ultralytics also honors device= at predict time
        self._loaded[task] = model
        return model


# --------------------------------------------------------------------------- #
# Engine (back-compat name: TakeoffAIInference)
# --------------------------------------------------------------------------- #
class InferenceEngine:
    """Singleton inference engine. Preserves the old TakeoffAIInference API."""

    _instance = None

    def __init__(self, model_path: str = "models/best.pt", device: str = "auto"):
        self.model_path = model_path
        self.registry = ModelRegistry(device=device)
        self.registry.register(ModelSpec(task="spaces", name="yolov8m-seg-v1.0", weights_path=model_path))
        self.model = None
        self._load_model()

    @classmethod
    def get_instance(cls, model_path: str = "models/best.pt", device: str = "auto"):
        if cls._instance is None:
            cls._instance = cls(model_path, device=device)
        return cls._instance

    @property
    def device(self) -> str:
        return self.registry.device_info.device

    @property
    def available(self) -> bool:
        return self.registry.available("spaces")

    def _load_model(self):
        """Best-effort eager load so startup logs report status; never fabricates."""
        try:
            if self.available:
                self.model = self.registry.load("spaces")
                print(f"[TakeoffAI] Model loaded: {self.model_path} on {self.device}")
            else:
                self.model = None
                print(f"[TakeoffAI] No trained model at {self.model_path} — "
                      f"raster AI disabled until weights are installed (vector AUTODETECT still works).")
        except ImportError:
            self.model = None
            print("[TakeoffAI] ultralytics not installed — raster AI disabled (no mock fallback).")

    def analyze(self, image_path: str, drawing_id: int = 0,
                conf: float = 0.35, iou: float = 0.45, *, tile: Optional[bool] = None) -> TakeoffAnalysis:
        """Run real detection. Raises ModelUnavailableError if no model is installed.

        ``tile``: force tiled inference on/off; ``None`` auto-tiles pages larger
        than DEFAULT_TILE_THRESHOLD (large construction sheets).
        """
        t0 = time.time()
        if not self.available:
            raise ModelUnavailableError(
                f"No trained model at {self.model_path}. Install weights "
                f"(see ai/models/README) or use vector AUTODETECT for PDFs."
            )
        detections = self._infer(image_path, conf, iou, tile=tile)
        rooms, doors, windows, walls, balconies, summary, avg = partition_detections(detections)
        return TakeoffAnalysis(
            drawing_id=drawing_id,
            processing_time_ms=int((time.time() - t0) * 1000),
            ai_model_version=self.registry.spec("spaces").name,
            rooms=rooms, doors=doors, windows=windows, walls=walls, balconies=balconies,
            summary=summary, quantities=raster_quantities(rooms, doors, windows, walls),
            confidence_avg=avg, model_available=True, status="ok", device=self.device,
        )

    # ---- lazy runtime (torch/cv2) — driven on the GPU box, not CI ---------- #
    def _infer(self, image_path: str, conf: float, iou: float, *, tile: Optional[bool]) -> list:
        model = self.model or self.registry.load("spaces")

        def run(img_or_path) -> list:
            results = model(img_or_path, conf=conf, iou=iou, device=self.device, verbose=False)
            return self._results_to_dets(results[0])

        should_tile = tile
        if should_tile is None:
            try:
                import cv2
                img = cv2.imread(image_path)
                h, w = img.shape[:2]
                should_tile = max(h, w) > DEFAULT_TILE_THRESHOLD
                if should_tile:
                    return run_tiled(img, lambda crop, t: self._results_to_dets(
                        model(crop, conf=conf, iou=iou, device=self.device, verbose=False)[0]),
                        iou_thr=iou)
            except ImportError:
                should_tile = False
        return run(image_path)

    @staticmethod
    def _results_to_dets(r) -> list:
        """Convert an ultralytics Result into normalized detection dicts."""
        dets: list = []
        if r.boxes is None:
            return dets
        for i, (box, cls_id, conf_val) in enumerate(zip(
            r.boxes.xyxy.tolist(), r.boxes.cls.tolist(), r.boxes.conf.tolist()
        )):
            name = CLASSES.get(int(cls_id), "unknown")
            x1, y1, x2, y2 = box
            det = {
                "id": f"{name[0]}{i}", "label": name,
                "bbox": [round(v, 1) for v in box],
                "confidence": round(float(conf_val), 3),
                "area": round((x2 - x1) * (y2 - y1), 1),
            }
            if getattr(r, "masks", None) and i < len(r.masks.xy):
                det["polygon"] = [[round(x, 2), round(y, 2)] for x, y in r.masks.xy[i].tolist()[::3]]
            dets.append(det)
        return dets


# Backward-compatible aliases — server.py / takeoff_routes.py import these names.
TakeoffAIInference = InferenceEngine
