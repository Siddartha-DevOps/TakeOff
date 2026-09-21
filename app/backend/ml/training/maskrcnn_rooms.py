"""Torchvision Mask R-CNN dataset/model helpers for COCO uncompressed RLE."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

from ml.datasets.adapt_swiss_rooms_maskrcnn_poc import decode_uncompressed_rle


class CocoRLEMaskDataset:
    """Lazy torchvision-compatible dataset; importing this module stays CPU-light."""

    def __init__(self, annotation_path: str | Path, image_root: str | Path):
        self.annotation_path = Path(annotation_path)
        self.image_root = Path(image_root)
        self.coco = json.loads(self.annotation_path.read_text(encoding="utf-8"))
        self.sharded = "floors" in self.coco
        self.annotations = defaultdict(list)
        if self.sharded:
            self.images = list(self.coco["floors"])
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

    def __getitem__(self, index):
        import torch

        floor_row = self.images[index]
        if self.sharded:
            shard_path = Path(floor_row["annotation_path"])
            if not shard_path.is_absolute():
                shard_path = self.annotation_path.parent / shard_path
            shard = json.loads(shard_path.read_text(encoding="utf-8"))
            image_row = shard["image"]
            annotations = sorted(shard["annotations"], key=lambda row: int(row["id"]))
            image_id = index + 1
        else:
            image_row = floor_row
            annotations = sorted(self.annotations[int(image_row["id"])], key=lambda row: int(row["id"]))
            image_id = int(image_row["id"])
        path = Path(image_row["file_name"])
        if not path.is_absolute():
            path = self.annotation_path.parent / path
        path = path.resolve()
        if not path.is_file():
            path = self.image_root / Path(image_row["file_name"]).name
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
        return image_tensor, target


def collate_fn(batch):
    return tuple(zip(*batch))


def build_maskrcnn(*, num_classes: int = 15, pretrained: bool = True):
    """Build Mask R-CNN R50-FPN v2; class zero is reserved for background."""
    from torchvision.models.detection import MaskRCNN_ResNet50_FPN_V2_Weights, maskrcnn_resnet50_fpn_v2
    from torchvision.models.detection.faster_rcnn import FastRCNNPredictor
    from torchvision.models.detection.mask_rcnn import MaskRCNNPredictor

    weights = MaskRCNN_ResNet50_FPN_V2_Weights.DEFAULT if pretrained else None
    model = maskrcnn_resnet50_fpn_v2(weights=weights, weights_backbone=None)
    box_features = model.roi_heads.box_predictor.cls_score.in_features
    model.roi_heads.box_predictor = FastRCNNPredictor(box_features, num_classes)
    mask_features = model.roi_heads.mask_predictor.conv5_mask.in_channels
    model.roi_heads.mask_predictor = MaskRCNNPredictor(mask_features, 256, num_classes)
    return model
