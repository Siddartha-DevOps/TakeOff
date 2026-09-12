"""Annotation format support — convert between COCO, YOLO-seg, and Label Studio."""

from .formats import (
    coco_to_yolo_seg,
    label_studio_to_rings,
    normalize_ring,
    parse_yolo_seg_line,
    validate_ring,
    yolo_seg_line,
)

__all__ = [
    "coco_to_yolo_seg",
    "label_studio_to_rings",
    "normalize_ring",
    "parse_yolo_seg_line",
    "validate_ring",
    "yolo_seg_line",
]
