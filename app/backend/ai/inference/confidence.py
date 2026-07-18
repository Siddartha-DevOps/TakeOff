"""
Confidence scoring, calibration, and NMS (mission item #9).

Raw model scores are not probabilities — a YOLO "0.9" is not a 90%-correct
guarantee, and different classes need different accept thresholds (a missed wall
costs more than a missed outlet). This module provides, all pure NumPy so it is
unit-tested without a model:

- per-class confidence thresholds (``apply_class_thresholds``)
- greedy NMS + IoU (``nms``, ``box_iou``) for de-duplicating detections
- temperature calibration (``fit_temperature`` / ``apply_temperature``) fit on
  the accept/reject signal already logged in ``CorrectionEvent``
- expected calibration error (``expected_calibration_error``) to track whether
  reported confidence matches real accuracy over releases
"""

from __future__ import annotations

import math
from typing import Optional, Sequence

import numpy as np


# --- thresholds ------------------------------------------------------------
def apply_class_thresholds(
    detections: Sequence[dict],
    thresholds: dict,
    default: float = 0.25,
    *,
    label_key: str = "label",
    score_key: str = "confidence",
) -> list[dict]:
    """Keep detections whose score clears their class's threshold.

    ``thresholds`` maps class label -> min confidence; classes absent from the
    map use ``default``. Detections missing a score are dropped (a detection
    with no confidence is not trustworthy).
    """
    kept = []
    for d in detections:
        score = d.get(score_key)
        if score is None:
            continue
        if score >= thresholds.get(d.get(label_key), default):
            kept.append(d)
    return kept


# --- IoU + NMS -------------------------------------------------------------
def box_iou(a: Sequence[float], b: Sequence[float]) -> float:
    """IoU of two ``[x1, y1, x2, y2]`` boxes."""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def nms(boxes: Sequence[Sequence[float]], scores: Sequence[float], iou_thr: float = 0.45) -> list[int]:
    """Greedy non-max suppression. Returns kept indices, highest score first."""
    order = sorted(range(len(boxes)), key=lambda i: scores[i], reverse=True)
    kept: list[int] = []
    for i in order:
        if all(box_iou(boxes[i], boxes[k]) <= iou_thr for k in kept):
            kept.append(i)
    return kept


# --- temperature calibration ----------------------------------------------
def apply_temperature(scores: Sequence[float], temperature: float) -> np.ndarray:
    """Temperature-scale confidences in logit space (T>1 softens, T<1 sharpens)."""
    if temperature <= 0:
        raise ValueError("temperature must be > 0")
    s = np.clip(np.asarray(scores, dtype=float), 1e-6, 1 - 1e-6)
    logits = np.log(s / (1 - s))
    return 1.0 / (1.0 + np.exp(-logits / temperature))


def _nll(scores: np.ndarray, correct: np.ndarray) -> float:
    """Binary negative log-likelihood of calibrated scores vs the correct flag."""
    p = np.clip(scores, 1e-6, 1 - 1e-6)
    return float(-np.mean(correct * np.log(p) + (1 - correct) * np.log(1 - p)))


def fit_temperature(
    scores: Sequence[float],
    correct: Sequence[bool],
    *,
    grid: Optional[Sequence[float]] = None,
) -> float:
    """Fit a single temperature minimizing NLL on (score, was-correct) pairs.

    ``correct`` is exactly the accept/reject signal in ``CorrectionEvent`` —
    accepted detection = correct, rejected = incorrect — so the model's reported
    confidence can be recalibrated to observed reality. Grid search keeps it
    dependency-free (no scipy) and deterministic.
    """
    s = np.asarray(scores, dtype=float)
    c = np.asarray(correct, dtype=float)
    if len(s) == 0:
        raise ValueError("need at least one sample to fit temperature")
    candidates = grid if grid is not None else [round(0.05 * k, 2) for k in range(1, 101)]
    return min(candidates, key=lambda t: _nll(apply_temperature(s, t), c))


def expected_calibration_error(
    scores: Sequence[float],
    correct: Sequence[bool],
    n_bins: int = 10,
) -> float:
    """Expected Calibration Error: mean |confidence - accuracy| over score bins.

    0.0 = perfectly calibrated (a bucket of 0.8-confidence detections is right
    80% of the time). This is the number to watch across model releases.
    """
    s = np.asarray(scores, dtype=float)
    c = np.asarray(correct, dtype=float)
    if len(s) == 0:
        return 0.0
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        in_bin = (s > lo) & (s <= hi) if lo > 0 else (s >= lo) & (s <= hi)
        n = int(in_bin.sum())
        if n == 0:
            continue
        ece += (n / len(s)) * abs(float(c[in_bin].mean()) - float(s[in_bin].mean()))
    return ece
