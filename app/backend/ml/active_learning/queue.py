"""
Active-learning review queue (Phase 6) — turn live DB signals into a labeling
priority list, closing the flywheel: serve → surface uncertain → correct → retrain.

Two signals per drawing feed ``rank_drawings_for_review`` (in ``sampler``):
- **model uncertainty** — mean AI-detection confidence (low = unsure)
- **human disagreement** — how many corrections rejected/relabeled/edited the AI
  output (a drawing the model keeps getting wrong is worth labeling)

The aggregation here is pure (operates on plain rows), so it is unit-tested
without a DB; ``routes/active_learning_routes.py`` supplies the rows from
``Detection`` / ``CorrectionEvent`` queries.
"""

from __future__ import annotations

from typing import Iterable, Optional

# Correction actions that mean the AI output was wrong (vs. a plain 'accept').
REJECTION_ACTIONS = {"reject", "relabel", "edit"}


def aggregate_drawing_stats(
    detection_rows: Iterable[tuple],
    correction_rows: Iterable[tuple],
) -> list[dict]:
    """Fold per-detection + per-correction rows into per-drawing stats.

    - ``detection_rows``: ``(drawing_id, confidence)`` for AI detections
      (confidence may be None → ignored in the mean but still counts toward
      ``n_detections``).
    - ``correction_rows``: ``(drawing_id, action)``.

    Returns ``[{drawing_id, mean_confidence, n_detections, n_rejections}]`` — the
    exact input ``rank_drawings_for_review`` expects.
    """
    counts: dict = {}
    conf_sum: dict = {}
    conf_n: dict = {}
    rejections: dict = {}

    for drawing_id, confidence in detection_rows:
        counts[drawing_id] = counts.get(drawing_id, 0) + 1
        if confidence is not None:
            conf_sum[drawing_id] = conf_sum.get(drawing_id, 0.0) + float(confidence)
            conf_n[drawing_id] = conf_n.get(drawing_id, 0) + 1

    for drawing_id, action in correction_rows:
        if drawing_id is None:
            continue
        counts.setdefault(drawing_id, 0)
        if action in REJECTION_ACTIONS:
            rejections[drawing_id] = rejections.get(drawing_id, 0) + 1

    stats = []
    for drawing_id in counts:
        n_conf = conf_n.get(drawing_id, 0)
        mean_conf = (conf_sum[drawing_id] / n_conf) if n_conf else 1.0  # no scores → treat as confident
        stats.append({
            "drawing_id": drawing_id,
            "mean_confidence": round(mean_conf, 4),
            "n_detections": counts[drawing_id],
            "n_rejections": rejections.get(drawing_id, 0),
        })
    return stats


def detection_items(detection_rows: Iterable[tuple]) -> list[dict]:
    """Shape ``(id, drawing_id, label, confidence)`` rows for ``select_batch``.

    Detections with no confidence are treated as maximally uncertain (0.0) —
    an unscored AI detection is exactly the kind of thing worth reviewing.
    """
    items = []
    for det_id, drawing_id, label, confidence in detection_rows:
        items.append({
            "id": det_id,
            "drawing_id": drawing_id,
            "label": label,
            "confidence": float(confidence) if confidence is not None else 0.0,
        })
    return items
