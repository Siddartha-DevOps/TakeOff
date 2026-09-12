"""
SAM2 zero-shot room bootstrap — the Phase 1 "AI MVP" starting point.

CLAUDE.md Phase 1 calls for "SAM2 zero-shot room detection" *before* any
fine-tuned model exists: segment the plan into candidate room regions with no
labeled data, render them on the canvas, and let the estimator accept / reject /
label. Those corrections become the first CorrectionEvents, which
``ml/training/export_corrections.py`` turns into the seed training set — so this
module bootstraps the whole flywheel from zero labels.

SAM2 is class-agnostic: it proposes *regions*, not room types. So detections
here carry ``label="space"`` (unclassified) at modest confidence; the human
names them. Output matches ``ai/inference_api.py``'s detection dict shape
(``id / label / bbox / polygon / area / confidence``) so the existing canvas and
accept/reject path render it unchanged.

Heavy deps (torch, sam2) are imported lazily inside ``run_sam2_zero_shot`` only;
everything above it is pure NumPy and unit-tested, so this file imports and its
geometry is testable on a laptop / in CI without a GPU or model weights.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

import numpy as np

# Default SAM2 checkpoint location (downloaded on the GPU box, never in CI).
SAM2_MODEL_DIR = Path(__file__).parent / "models" / "sam2"
SAM2_CHECKPOINT = SAM2_MODEL_DIR / "sam2_hiera_large.pt"

# A class-agnostic region proposal has no room type yet.
UNCLASSIFIED_LABEL = "space"


# --------------------------------------------------------------------------- #
# Pure geometry helpers (NumPy only) — unit-tested, no torch / no GPU.
# --------------------------------------------------------------------------- #
def point_prompt_grid(width: int, height: int, n_per_side: int = 16) -> list[list[int]]:
    """An interior ``n_per_side`` × ``n_per_side`` grid of SAM2 point prompts.

    Points are inset from the page edges (the (k+0.5)/n rule) so no prompt lands
    on the border, and returned as ``[x, y]`` integer pixel coordinates.
    """
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")
    if n_per_side <= 0:
        raise ValueError("n_per_side must be positive")
    pts: list[list[int]] = []
    for j in range(n_per_side):
        for i in range(n_per_side):
            x = int((i + 0.5) / n_per_side * width)
            y = int((j + 0.5) / n_per_side * height)
            pts.append([x, y])
    return pts


def mask_bbox(mask: np.ndarray) -> Optional[list[int]]:
    """Axis-aligned ``[x1, y1, x2, y2]`` of a boolean mask, or None if empty."""
    m = np.asarray(mask).astype(bool)
    if not m.any():
        return None
    ys, xs = np.where(m)
    return [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]


def mask_area(mask: np.ndarray) -> int:
    """Number of set pixels in a boolean mask."""
    return int(np.asarray(mask).astype(bool).sum())


def mask_iou(a: np.ndarray, b: np.ndarray) -> float:
    """Intersection-over-union of two boolean masks (0.0 if both empty)."""
    a = np.asarray(a).astype(bool)
    b = np.asarray(b).astype(bool)
    inter = int(np.logical_and(a, b).sum())
    union = int(np.logical_or(a, b).sum())
    return inter / union if union else 0.0


def nms_masks(masks: Sequence[np.ndarray], scores: Sequence[float], iou_thr: float = 0.5) -> list[int]:
    """Greedy mask NMS. Returns kept indices, highest score first.

    SAM2's point grid fires many prompts inside one room, yielding near-duplicate
    masks; this collapses them so each region is proposed once.
    """
    order = sorted(range(len(masks)), key=lambda i: scores[i], reverse=True)
    kept: list[int] = []
    for i in order:
        if all(mask_iou(masks[i], masks[k]) <= iou_thr for k in kept):
            kept.append(i)
    return kept


def filter_by_area(
    masks: Sequence[np.ndarray],
    page_area: float,
    min_frac: float = 0.005,
    max_frac: float = 0.6,
) -> list[int]:
    """Indices of masks whose area is a plausible room fraction of the page.

    Drops specks (< ``min_frac``, e.g. symbols/text) and page-spanning blobs
    (> ``max_frac``, e.g. the whole sheet or the building outline).
    """
    if page_area <= 0:
        raise ValueError("page_area must be positive")
    keep: list[int] = []
    for i, m in enumerate(masks):
        frac = mask_area(m) / page_area
        if min_frac <= frac <= max_frac:
            keep.append(i)
    return keep


def bbox_to_ring(bbox: Sequence[float]) -> list[list[float]]:
    """Rectangle ring ``[[x1,y1],[x2,y1],[x2,y2],[x1,y2]]`` from a bbox."""
    x1, y1, x2, y2 = bbox
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


def masks_to_detections(
    masks: Sequence[np.ndarray],
    scores: Sequence[float],
    *,
    rings: Optional[Sequence[Optional[Sequence[Sequence[float]]]]] = None,
    label: str = UNCLASSIFIED_LABEL,
) -> list[dict]:
    """Convert filtered SAM2 masks into inference_api-shaped detection dicts.

    ``rings`` optionally supplies a traced polygon per mask (from cv2 contours on
    the GPU box); when absent the bbox rectangle is used, which the canvas still
    renders and the user can reshape. Coordinates are plan-space pixels, matching
    ``Detection.geom`` / ``ai/preprocessing.py``.
    """
    dets: list[dict] = []
    for i, m in enumerate(masks):
        box = mask_bbox(m)
        if box is None:
            continue
        ring = None
        if rings is not None and rings[i]:
            ring = [[round(float(x), 2), round(float(y), 2)] for x, y in rings[i]]
        else:
            ring = [[float(x), float(y)] for x, y in bbox_to_ring(box)]
        x1, y1, x2, y2 = box
        dets.append(
            {
                "id": f"s{i}",
                "label": label,
                "bbox": [float(x1), float(y1), float(x2), float(y2)],
                "polygon": ring,
                "area": float(mask_area(m)),
                "confidence": round(float(scores[i]), 3),
                "source": "sam2_zero_shot",
            }
        )
    return dets


# --------------------------------------------------------------------------- #
# Orchestration — lazy torch/sam2, runs only on a GPU box with weights.
# --------------------------------------------------------------------------- #
def sam2_weights_available() -> bool:
    """True when a SAM2 checkpoint is installed (never in CI)."""
    return SAM2_CHECKPOINT.exists()


def run_sam2_zero_shot(
    image_path: str,
    *,
    n_per_side: int = 16,
    iou_thr: float = 0.5,
    min_area_frac: float = 0.005,
    max_area_frac: float = 0.6,
    checkpoint: Optional[str] = None,
) -> dict:
    """Segment a rasterized plan into candidate room regions with zero-shot SAM2.

    Returns ``{"status": "ok", "rooms": [...], "model": "sam2_zero_shot"}`` on
    success, or ``{"status": "needs_weights", ...}`` when SAM2 / its checkpoint
    is unavailable — mirroring ``ai/detect_symbols.py`` so callers degrade
    gracefully before the model is installed.

    The heavy path (torch, sam2, image load) is intentionally isolated here; the
    geometry above is pure and independently tested.
    """
    ckpt = Path(checkpoint) if checkpoint else SAM2_CHECKPOINT
    if not ckpt.exists():
        return {"status": "needs_weights", "rooms": [], "model": "sam2_zero_shot",
                "detail": f"SAM2 checkpoint not found at {ckpt}"}

    try:  # heavy, GPU-only imports — kept out of module import / CI
        import cv2  # noqa: F401
        from sam2.build_sam import build_sam2  # type: ignore
        from sam2.automatic_mask_generator import SAM2AutomaticMaskGenerator  # type: ignore
    except ImportError as exc:
        return {"status": "needs_weights", "rooms": [], "model": "sam2_zero_shot",
                "detail": f"SAM2 runtime not installed: {exc}"}

    image = cv2.cvtColor(cv2.imread(image_path), cv2.COLOR_BGR2RGB)  # type: ignore
    h, w = image.shape[:2]

    sam2 = build_sam2(SAM2_MODEL_DIR / "sam2_hiera_l.yaml", str(ckpt))
    generator = SAM2AutomaticMaskGenerator(sam2, points_per_side=n_per_side)
    raw = generator.generate(image)  # [{"segmentation": bool[H,W], "predicted_iou": float}, ...]

    masks = [r["segmentation"] for r in raw]
    scores = [float(r.get("predicted_iou", 0.0)) for r in raw]

    keep = filter_by_area(masks, page_area=float(w * h),
                          min_frac=min_area_frac, max_frac=max_area_frac)
    keep = [keep[i] for i in nms_masks([masks[k] for k in keep],
                                       [scores[k] for k in keep], iou_thr=iou_thr)]

    rings = []
    for k in keep:
        contours, _ = cv2.findContours(masks[k].astype("uint8"),  # type: ignore
                                        cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        rings.append(max(contours, key=cv2.contourArea).reshape(-1, 2).tolist() if contours else None)

    rooms = masks_to_detections([masks[k] for k in keep], [scores[k] for k in keep], rings=rings)
    return {"status": "ok", "rooms": rooms, "model": "sam2_zero_shot", "page": {"width": w, "height": h}}
