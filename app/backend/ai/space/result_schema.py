"""Stable JSON shaping for Ultralytics segmentation results."""

from __future__ import annotations

from typing import Any


def _list(value: Any) -> list:
    for method in ("detach", "cpu"):
        if hasattr(value, method):
            value = getattr(value, method)()
    return value.tolist() if hasattr(value, "tolist") else list(value)


def serialize_result(result: Any) -> dict:
    """Convert one Ultralytics result into transport-safe detections."""
    boxes = getattr(result, "boxes", None)
    if boxes is None:
        return {"image_width": 0, "image_height": 0, "detections": []}

    class_ids = [int(value) for value in _list(boxes.cls)]
    confidences = [float(value) for value in _list(boxes.conf)]
    xyxy = _list(boxes.xyxy)
    names = getattr(result, "names", {})
    shape = getattr(result, "orig_shape", (0, 0))
    height, width = int(shape[0]), int(shape[1])
    mask_data = getattr(getattr(result, "masks", None), "xyn", None) or []

    detections = []
    for index, class_id in enumerate(class_ids):
        if isinstance(names, dict):
            class_name = names.get(class_id, str(class_id))
        else:
            class_name = names[class_id] if class_id < len(names) else str(class_id)
        polygon = _list(mask_data[index]) if index < len(mask_data) else []
        detections.append({
            "class_id": class_id,
            "class_name": str(class_name),
            "confidence": round(confidences[index], 6),
            "bbox_xyxy": [round(float(value), 3) for value in xyxy[index]],
            "polygon_normalized": [
                [round(float(point[0]), 6), round(float(point[1]), 6)]
                for point in polygon
            ],
        })

    return {
        "image_width": width,
        "image_height": height,
        "detections": detections,
    }
