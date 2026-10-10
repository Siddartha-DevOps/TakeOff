"""Torchvision Mask R-CNN dataset/model helpers for COCO uncompressed RLE."""

from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image



def decode_uncompressed_rle(rle: dict) -> np.ndarray:
    """Decode deterministic COCO uncompressed RLE without pycocotools."""
    height, width = map(int, rle["size"])
    counts = np.asarray(rle["counts"], dtype=np.int64)
    if np.any(counts < 0) or int(counts.sum()) != height * width:
        raise ValueError("RLE counts do not cover the declared mask")
    values = np.repeat(np.arange(counts.size, dtype=np.uint8) % 2, counts)
    return values.reshape((height, width), order="F")


def _portable_basename(value: str | Path) -> str:
    name = str(value).replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    if not name:
        raise ValueError(f"asset path has no filename: {value!r}")
    return name


def _rss_bytes() -> int | None:
    try:
        import psutil

        return int(psutil.Process(os.getpid()).memory_info().rss)
    except (ImportError, OSError):
        return None


def _emit_dataset_diagnostic(event: str, metadata: dict) -> None:
    print(json.dumps({
        "event": event,
        "pid": os.getpid(),
        "cpu_rss_bytes": _rss_bytes(),
        **metadata,
    }, sort_keys=True), flush=True)


class CocoRLEMaskDataset:
    """Lazy torchvision-compatible dataset; importing this module stays CPU-light."""

    def __init__(
        self, annotation_path: str | Path, image_root: str | Path, *,
        split: str | None = None, diagnostic_logging: bool = False,
    ):
        self.annotation_path = Path(annotation_path)
        self.image_root = Path(image_root)
        self.coco = json.loads(self.annotation_path.read_text(encoding="utf-8"))
        self.sharded = "floors" in self.coco
        self.diagnostic_logging = diagnostic_logging
        self.annotations = defaultdict(list)
        if self.sharded:
            self.images = [
                row for row in self.coco["floors"]
                if split is None or row.get("split") == split
            ]
            category_ids = {int(row["id"]) for row in self.coco["taxonomy"]}
        else:
            self.images = sorted(self.coco["images"], key=lambda row: int(row["id"]))
            for annotation in self.coco["annotations"]:
                self.annotations[int(annotation["image_id"])].append(annotation)
            category_ids = {int(row["id"]) for row in self.coco["categories"]}
        if category_ids != set(range(1, 15)):
            raise ValueError("Mask R-CNN POC must contain the frozen 14-class taxonomy")

    def __len__(self):
        return len(self.images)

    def _shard_path(self, floor_row):
        path = Path(floor_row["annotation_path"])
        if not path.is_file():
            path = (
                self.annotation_path.parent / "annotations" / floor_row["split"] /
                _portable_basename(floor_row["annotation_path"])
            )
        return path

    def _image_path(self, floor_row, image_row):
        path = Path(image_row["file_name"])
        if not path.is_file():
            split_name = floor_row.get("split") or image_row.get("split")
            basename = _portable_basename(image_row["file_name"])
            split_candidate = self.image_root / str(split_name) / basename
            flat_candidate = self.image_root / basename
            path = split_candidate if split_candidate.is_file() else flat_candidate
        return path.resolve()

    def __getitem__(self, index):
        import torch

        floor_row = self.images[index]
        metadata = {
            "dataset_index": index,
            "split": floor_row.get("split"),
            "floor_key": floor_row.get("floor_key"),
            "site_id": floor_row.get("site_id"),
            "building_id": floor_row.get("building_id"),
            "plan_id": floor_row.get("plan_id"),
            "floor_id": floor_row.get("floor_id"),
            "authoritative_instances": floor_row.get("authoritative_instance_count"),
        }
        if self.diagnostic_logging:
            _emit_dataset_diagnostic("sample_load_start", metadata)
        if self.sharded:
            shard_path = self._shard_path(floor_row)
            shard = json.loads(shard_path.read_text(encoding="utf-8"))
            image_row = shard["image"]
            annotations = sorted(shard["annotations"], key=lambda row: int(row["id"]))
            image_id = index + 1
        else:
            image_row = floor_row
            annotations = sorted(self.annotations[int(image_row["id"])], key=lambda row: int(row["id"]))
            image_id = int(image_row["id"])
        path = self._image_path(floor_row, image_row)
        metadata.update({
            "image_path": str(path),
            "image_width": int(image_row["width"]),
            "image_height": int(image_row["height"]),
            "instances": len(annotations),
        })
        with Image.open(path) as image:
            array = np.asarray(image.convert("RGB"), dtype=np.uint8).copy()
        image_tensor = torch.from_numpy(array).permute(2, 0, 1).float().div(255)
        masks = [decode_uncompressed_rle(row["segmentation"]) for row in annotations]
        if masks:
            mask_tensor = torch.from_numpy(np.stack(masks)).to(torch.uint8)
            boxes = torch.tensor([
                [row["bbox"][0], row["bbox"][1], row["bbox"][0] + row["bbox"][2], row["bbox"][1] + row["bbox"][3]]
                for row in annotations
            ], dtype=torch.float32)
        else:
            height, width = int(image_row["height"]), int(image_row["width"])
            mask_tensor = torch.zeros((0, height, width), dtype=torch.uint8)
            boxes = torch.zeros((0, 4), dtype=torch.float32)
        target = {
            "boxes": boxes,
            "labels": torch.tensor([row["category_id"] for row in annotations], dtype=torch.int64),
            "masks": mask_tensor,
            "image_id": torch.tensor([image_id], dtype=torch.int64),
            "area": torch.tensor([row["area"] for row in annotations], dtype=torch.float32),
            "iscrowd": torch.zeros((len(annotations),), dtype=torch.int64),
        }
        if self.diagnostic_logging:
            target["_diagnostic"] = metadata
            _emit_dataset_diagnostic("sample_load_complete", metadata)
        return image_tensor, target


def collate_fn(batch):
    return tuple(zip(*batch))


def build_maskrcnn(
    *, num_classes: int = 15, pretrained: bool = True,
    initialization_checkpoint: str | Path | None = None,
    min_size: int = 1024, max_size: int = 1600,
):
    """Build Mask R-CNN R50-FPN v2; class zero is reserved for background."""
    from torchvision.models.detection import MaskRCNN_ResNet50_FPN_V2_Weights, maskrcnn_resnet50_fpn_v2
    from torchvision.models.detection.faster_rcnn import FastRCNNPredictor
    from torchvision.models.detection.mask_rcnn import MaskRCNNPredictor

    if pretrained and initialization_checkpoint is not None:
        raise ValueError("choose either torchvision download or a pinned checkpoint, not both")
    weights = MaskRCNN_ResNet50_FPN_V2_Weights.DEFAULT if pretrained else None
    model = maskrcnn_resnet50_fpn_v2(
        weights=weights, weights_backbone=None,
        min_size=min_size, max_size=max_size,
    )
    if initialization_checkpoint is not None:
        import torch

        state = torch.load(Path(initialization_checkpoint), map_location="cpu", weights_only=True)
        model.load_state_dict(state, strict=True)
    box_features = model.roi_heads.box_predictor.cls_score.in_features
    model.roi_heads.box_predictor = FastRCNNPredictor(box_features, num_classes)
    mask_features = model.roi_heads.mask_predictor.conv5_mask.in_channels
    model.roi_heads.mask_predictor = MaskRCNNPredictor(mask_features, 256, num_classes)
    return model
