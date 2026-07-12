"""
Accuracy metrics for the golden-set eval harness (ml/eval/harness.py).

These gate model promotion, so they are exact, standard, and pure (no DB, no
GPU): polygon/box IoU, segmentation mean-IoU, real all-point Average Precision
(mAP@0.5, COCO/VOC-2010 style — not a proxy), and measurement-error %.

Complements the live `eval_harness.py`, which scores the model against user
CorrectionEvents (a drifting signal). This module scores against a *fixed*
labeled golden set, which is what defensible release gating needs
(memory/TOGAL_PARITY_REAUDIT.md §5: ~70% time savings, within ~5% quantity
margin — tracked per release as mIoU / mAP / measurement-error).
"""

from __future__ import annotations

from typing import Optional, Sequence

import numpy as np

Point = Sequence[float]
Ring = Sequence[Point]
Bbox = Sequence[float]  # [x1, y1, x2, y2]


# ──────────────────────────────────────────────────────────────
# IoU
# ──────────────────────────────────────────────────────────────
def poly_iou(a: Ring, b: Ring) -> float:
    """Intersection-over-union of two polygon rings (plan-space coords)."""
    from shapely.geometry import Polygon

    pa, pb = Polygon(a), Polygon(b)
    if not pa.is_valid:
        pa = pa.buffer(0)
    if not pb.is_valid:
        pb = pb.buffer(0)
    if pa.is_empty or pb.is_empty:
        return 0.0
    inter = pa.intersection(pb).area
    union = pa.area + pb.area - inter
    return float(inter / union) if union > 0 else 0.0


def box_iou(a: Bbox, b: Bbox) -> float:
    """IoU of two axis-aligned boxes [x1, y1, x2, y2]."""
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - inter
    return float(inter / union) if union > 0 else 0.0


# ──────────────────────────────────────────────────────────────
# Segmentation mean IoU
# ──────────────────────────────────────────────────────────────
def mean_iou(gt_polys: Sequence[Ring], pred_polys: Sequence[Ring], iou_fn=poly_iou) -> Optional[float]:
    """Mean IoU over ground-truth polygons (rooms/spaces).

    Each GT is greedily matched to the best still-unused prediction; an unmatched
    GT contributes 0 (a miss is a real accuracy hit). Returns None if there are no
    GT polygons (undefined — the harness skips the image rather than count it).
    """
    if not gt_polys:
        return None
    used: set[int] = set()
    ious: list[float] = []
    for g in gt_polys:
        best_iou, best_j = 0.0, -1
        for j, p in enumerate(pred_polys):
            if j in used:
                continue
            i = iou_fn(g, p)
            if i > best_iou:
                best_iou, best_j = i, j
        if best_j >= 0 and best_iou > 0:
            used.add(best_j)
        ious.append(best_iou)
    return float(sum(ious) / len(ious))


# ──────────────────────────────────────────────────────────────
# Average Precision (real, all-point interpolation)
# ──────────────────────────────────────────────────────────────
def ap_from_pr_curve(recalls, precisions) -> float:
    """All-point-interpolated AP (COCO/VOC-2010) from a precision-recall curve.

    Shared by single-image AP and the harness's image-scoped global mAP so both
    integrate the curve identically.
    """
    mrec = np.concatenate(([0.0], np.asarray(recalls, dtype=float), [1.0]))
    mpre = np.concatenate(([0.0], np.asarray(precisions, dtype=float), [0.0]))
    for i in range(len(mpre) - 1, 0, -1):
        mpre[i - 1] = max(mpre[i - 1], mpre[i])
    idx = np.where(mrec[1:] != mrec[:-1])[0]
    return float(np.sum((mrec[idx + 1] - mrec[idx]) * mpre[idx + 1]))


def average_precision(
    preds: Sequence[dict],
    gts: Sequence,
    iou_fn=box_iou,
    iou_thr: float = 0.5,
) -> Optional[float]:
    """AP for one class in one image. `preds` = [{"score", "geom"}...]; `gts` = [geom...].

    Standard detection AP: sort predictions by score, greedily match each to an
    unused GT at IoU >= threshold (TP) else FP, build the precision-recall curve,
    and integrate it with all-point interpolation. Returns None when there is no
    GT for the class (undefined; excluded from the mean).
    """
    if not gts:
        return None
    if not preds:
        return 0.0

    order = sorted(preds, key=lambda p: -p["score"])
    matched = [False] * len(gts)
    tp = np.zeros(len(order))
    fp = np.zeros(len(order))

    for i, p in enumerate(order):
        best_iou, best_j = 0.0, -1
        for j, g in enumerate(gts):
            if matched[j]:
                continue
            iou = iou_fn(p["geom"], g)
            if iou > best_iou:
                best_iou, best_j = iou, j
        if best_iou >= iou_thr and best_j >= 0:
            matched[best_j] = True
            tp[i] = 1
        else:
            fp[i] = 1

    tp_c = np.cumsum(tp)
    fp_c = np.cumsum(fp)
    recalls = tp_c / len(gts)
    precisions = tp_c / np.maximum(tp_c + fp_c, np.finfo(np.float64).eps)
    return ap_from_pr_curve(recalls, precisions)


def mean_average_precision(
    preds_by_class: dict[str, Sequence[dict]],
    gts_by_class: dict[str, Sequence],
    iou_fn=box_iou,
    iou_thr: float = 0.5,
) -> Optional[float]:
    """mAP@iou_thr = mean of per-class AP over classes that have ground truth."""
    aps: list[float] = []
    for cls, gts in gts_by_class.items():
        ap = average_precision(preds_by_class.get(cls, []), gts, iou_fn, iou_thr)
        if ap is not None:
            aps.append(ap)
    return float(sum(aps) / len(aps)) if aps else None


# ──────────────────────────────────────────────────────────────
# Measurement error
# ──────────────────────────────────────────────────────────────
def measurement_error_pct(pred_totals: dict[str, float], gt_totals: dict[str, float]) -> Optional[float]:
    """Mean absolute percentage error of predicted vs ground-truth quantities.

    Keyed by quantity name (e.g. "floor_area_sqft", "wall_lf", "door_count").
    The headline number in the reaudit's "within ~5%" gate. Returns None if no
    ground-truth quantities are provided.
    """
    errs: list[float] = []
    for key, gt in gt_totals.items():
        if gt == 0:
            continue
        pred = pred_totals.get(key, 0.0)
        errs.append(abs(pred - gt) / abs(gt) * 100.0)
    return round(float(sum(errs) / len(errs)), 2) if errs else None
