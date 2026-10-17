"""Torchvision Mask R-CNN room inference behind the existing takeoff contract.

The training stack lives under ``ml.training``; this module is the deliberately
small serving adapter.  Torch and torchvision remain lazy optional runtime
dependencies, while a predictor can be injected at the external-model boundary
for deterministic end-to-end tests.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable, Mapping, Optional

import numpy as np
from PIL import Image

from .device import resolve_device
from .engine import (
    ModelUnavailableError,
    TakeoffAnalysis,
    partition_detections,
    raster_quantities,
)

ROOM_CLASSES = {
    1: "bedroom",
    2: "bathroom",
    3: "kitchen",
    4: "living",
    5: "living_dining",
    6: "corridor",
    7: "storage",
    8: "balcony",
    9: "office",
    10: "utility",
    11: "stairs",
    12: "entry_lobby",
    13: "generic_room",
    14: "shaft",
}


def _array(value) -> np.ndarray:
    """Detach a torch-like value without importing torch in the API image."""
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        value = value.numpy()
    return np.asarray(value)


def _ring_area(points: list[list[float]]) -> float:
    return (
        abs(
            sum(
                points[index][0] * points[(index + 1) % len(points)][1]
                - points[(index + 1) % len(points)][0] * points[index][1]
                for index in range(len(points))
            )
        )
        / 2.0
    )


def _signed_ring_area(points: list[list[float]]) -> float:
    return (
        sum(
            points[index][0] * points[(index + 1) % len(points)][1]
            - points[(index + 1) % len(points)][0] * points[index][1]
            for index in range(len(points))
        )
        / 2.0
    )


def _simplify_grid_ring(points: list[list[float]]) -> list[list[float]]:
    simplified = []
    for point in points:
        while len(simplified) >= 2:
            a, b = simplified[-2], simplified[-1]
            if (b[0] - a[0]) * (point[1] - b[1]) != (b[1] - a[1]) * (point[0] - b[0]):
                break
            simplified.pop()
        simplified.append(point)
    if len(simplified) > 3:
        changed = True
        while changed and len(simplified) > 3:
            changed = False
            a, b, c = simplified[-2], simplified[-1], simplified[0]
            if (b[0] - a[0]) * (c[1] - b[1]) == (b[1] - a[1]) * (c[0] - b[0]):
                simplified.pop()
                changed = True
            a, b, c = simplified[-1], simplified[0], simplified[1]
            if (b[0] - a[0]) * (c[1] - b[1]) == (b[1] - a[1]) * (c[0] - b[0]):
                simplified.pop(0)
                changed = True
    return simplified


def _mask_components(mask: np.ndarray, threshold: float) -> list[dict]:
    """Vectorize pixel-cell boundaries without adding a serving dependency."""
    binary = (np.squeeze(mask) >= threshold).astype(np.uint8)
    if binary.ndim != 2 or not binary.any():
        return []

    height, width = binary.shape
    edges = set()
    for y, x in np.argwhere(binary):
        x, y = int(x), int(y)
        if y == 0 or not binary[y - 1, x]:
            edges.add(((x, y), (x + 1, y)))
        if x == width - 1 or not binary[y, x + 1]:
            edges.add(((x + 1, y), (x + 1, y + 1)))
        if y == height - 1 or not binary[y + 1, x]:
            edges.add(((x + 1, y + 1), (x, y + 1)))
        if x == 0 or not binary[y, x - 1]:
            edges.add(((x, y + 1), (x, y)))

    rings = []
    while edges:
        start = min(edges)
        edge = start
        ring = [list(edge[0])]
        while True:
            edges.remove(edge)
            ring.append(list(edge[1]))
            if edge[1] == start[0]:
                break
            candidates = sorted(
                candidate for candidate in edges if candidate[0] == edge[1]
            )
            if not candidates:
                raise ValueError("Mask boundary is not a closed ring")
            edge = candidates[0]
        ring.pop()  # geometry rings are implicitly closed throughout TakeOff
        ring = _simplify_grid_ring(ring)
        if len(ring) >= 3:
            rings.append(ring)

    exteriors = [ring for ring in rings if _signed_ring_area(ring) > 0]
    holes = [ring for ring in rings if _signed_ring_area(ring) < 0]
    components = []
    for exterior in exteriors:
        ext_bounds = (
            min(point[0] for point in exterior),
            min(point[1] for point in exterior),
            max(point[0] for point in exterior),
            max(point[1] for point in exterior),
        )
        component_holes = []
        for hole in holes:
            hx = sum(point[0] for point in hole) / len(hole)
            hy = sum(point[1] for point in hole) / len(hole)
            if (
                ext_bounds[0] <= hx <= ext_bounds[2]
                and ext_bounds[1] <= hy <= ext_bounds[3]
            ):
                component_holes.append(hole)
        net_area = _ring_area(exterior) - sum(
            _ring_area(ring) for ring in component_holes
        )
        if net_area <= 0:
            continue
        components.append(
            {"polygon": exterior, "holes": component_holes, "area": net_area}
        )
    components.sort(
        key=lambda item: (
            min(point[1] for point in item["polygon"]),
            min(point[0] for point in item["polygon"]),
        )
    )
    return components


def maskrcnn_output_to_detections(
    output: Mapping,
    *,
    score_threshold: float = 0.5,
    mask_threshold: float = 0.5,
    class_map: Optional[Mapping[int, str]] = None,
) -> list[dict]:
    """Convert one torchvision prediction into the established room schema."""
    class_map = class_map or ROOM_CLASSES
    boxes = _array(output.get("boxes", [])).reshape(-1, 4)
    labels = _array(output.get("labels", [])).reshape(-1)
    scores = _array(output.get("scores", [])).reshape(-1)
    masks = _array(output.get("masks", []))
    if not (len(boxes) == len(labels) == len(scores) == len(masks)):
        raise ValueError("Mask R-CNN output boxes/labels/scores/masks do not reconcile")

    detections = []
    for prediction_index, (box, label_value, score_value, mask) in enumerate(
        zip(boxes, labels, scores, masks)
    ):
        score = float(score_value)
        label_id = int(label_value)
        if score < score_threshold or label_id not in class_map:
            continue
        components = _mask_components(mask, mask_threshold)
        for component_index, component in enumerate(components):
            polygon = component["polygon"]
            xs = [point[0] for point in polygon]
            ys = [point[1] for point in polygon]
            suffix = f"-{component_index}" if len(components) > 1 else ""
            detection = {
                "id": f"mask-room-{prediction_index}{suffix}",
                "label": class_map[label_id],
                "class_id": label_id,
                "bbox": [min(xs), min(ys), max(xs), max(ys)],
                "confidence": round(score, 6),
                "area": round(float(component["area"]), 4),
                "polygon": polygon,
            }
            if component["holes"]:
                detection["holes"] = component["holes"]
            detections.append(detection)
    return detections


class MaskRCNNInference:
    """Mask R-CNN implementation of the existing ``analyze`` engine contract."""

    backend = "maskrcnn"

    def __init__(
        self,
        weights_path: str,
        *,
        device: str = "auto",
        score_threshold: float = 0.5,
        mask_threshold: float = 0.5,
        predictor: Optional[Callable[[np.ndarray], Mapping]] = None,
        model_version: str = "maskrcnn-resnet50-fpn-v2-rooms-v1",
    ):
        self.weights_path = str(weights_path)
        self.device = resolve_device(device).device
        self.score_threshold = score_threshold
        self.mask_threshold = mask_threshold
        self.model_version = model_version
        self._predictor = predictor
        self.model = None

    @property
    def available(self) -> bool:
        return self._predictor is not None or Path(self.weights_path).is_file()

    def _load_model(self):
        if self.model is not None:
            return self.model
        if not Path(self.weights_path).is_file():
            raise ModelUnavailableError(f"No Mask R-CNN weights at {self.weights_path}")
        import torch
        from ml.training.maskrcnn_rooms import build_maskrcnn

        checkpoint = torch.load(
            self.weights_path, map_location="cpu", weights_only=False
        )
        state = checkpoint.get("model", checkpoint.get("model_state_dict", checkpoint))
        model = build_maskrcnn(num_classes=15, pretrained=False)
        model.load_state_dict(state, strict=True)
        model.to(self.device)
        model.eval()
        self.model = model
        return model

    def _predict(self, image: np.ndarray) -> Mapping:
        if self._predictor is not None:
            return self._predictor(image)
        import torch

        model = self._load_model()
        tensor = (
            torch.from_numpy(image.copy())
            .permute(2, 0, 1)
            .float()
            .div(255)
            .to(self.device)
        )
        with torch.inference_mode():
            return model([tensor])[0]

    def analyze(
        self, image_path: str, drawing_id: int = 0, **_kwargs
    ) -> TakeoffAnalysis:
        if not self.available:
            raise ModelUnavailableError(f"No Mask R-CNN weights at {self.weights_path}")
        started = time.time()
        with Image.open(image_path) as source:
            image = np.asarray(source.convert("RGB"), dtype=np.uint8)
        detections = maskrcnn_output_to_detections(
            self._predict(image),
            score_threshold=self.score_threshold,
            mask_threshold=self.mask_threshold,
        )
        rooms, doors, windows, walls, balconies, summary, confidence = (
            partition_detections(detections)
        )
        return TakeoffAnalysis(
            drawing_id=drawing_id,
            processing_time_ms=int((time.time() - started) * 1000),
            ai_model_version=self.model_version,
            rooms=rooms,
            doors=doors,
            windows=windows,
            walls=walls,
            balconies=balconies,
            summary=summary,
            quantities=raster_quantities(rooms, doors, windows, walls),
            confidence_avg=confidence,
            model_available=True,
            status="ok",
            device=self.device,
        )
