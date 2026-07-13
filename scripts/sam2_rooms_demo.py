"""SAM2 zero-shot room detection — demoable today."""
import torch
from sam2.build_sam import build_sam2
from sam2.automatic_mask_generator import SAM2AutomaticMaskGenerator
from PIL import Image
import numpy as np

# Download checkpoint: https://github.com/facebookresearch/sam2
checkpoint = "sam2.1_hiera_large.pt"
model_cfg = "configs/sam2.1/sam2.1_hiera_l.yaml"

sam2 = build_sam2(model_cfg, checkpoint, device="cuda")
mask_generator = SAM2AutomaticMaskGenerator(
    model=sam2,
    points_per_side=32,
    pred_iou_thresh=0.7,
    stability_score_thresh=0.85,
    min_mask_region_area=1000,   # filter tiny noise
)

image = np.array(Image.open("test_floorplan.png"))
masks = mask_generator.generate(image)

# Each mask = {"segmentation": np.array, "area": int, "bbox": [...], ...}
# These are unlabeled — SAM gives you shapes, not room types
print(f"Found {len(masks)} regions")
