"""
Active learning query strategies (mission item #10).

Labeling budget is scarce, so spend it where the model is *most wrong or most
unsure*, not on random sheets. This module scores unlabeled/low-signal items by
uncertainty and selects a diverse batch to send to annotation — closing the
flywheel: predict → surface uncertain → label → retrain.

Two complementary signals:
- **Model uncertainty** on a detection (least-confidence / margin / entropy).
- **Human disagreement** on a drawing — how often the AI's detections there were
  *rejected/edited* in ``CorrectionEvent`` (a drawing the model keeps getting
  wrong is worth labeling densely).

Pure NumPy/stdlib — unit-tested, no model or DB.
"""

from __future__ import annotations

import math
from typing import Callable, Optional, Sequence


# --- per-detection uncertainty --------------------------------------------
def least_confidence(score: float) -> float:
    """1 - top-class probability. Higher = more uncertain."""
    return 1.0 - float(score)


def margin_confidence(top1: float, top2: float) -> float:
    """Uncertainty as 1 - (p1 - p2); a small top-1/top-2 margin = ambiguous class."""
    return 1.0 - (float(top1) - float(top2))


def entropy(probs: Sequence[float]) -> float:
    """Shannon entropy (nats) of a class-probability vector. Higher = more uncertain."""
    total = sum(probs)
    if total <= 0:
        return 0.0
    h = 0.0
    for p in probs:
        q = p / total
        if q > 0:
            h -= q * math.log(q)
    return h


# --- ranking + batched selection ------------------------------------------
def uncertainty_rank(
    items: Sequence[dict],
    *,
    score_key: str = "confidence",
    strategy: str = "least_confidence",
) -> list[dict]:
    """Return items sorted most-uncertain first under the chosen strategy.

    ``strategy`` ∈ {"least_confidence", "margin", "entropy"}. ``margin`` reads
    ``top1``/``top2`` keys; ``entropy`` reads a ``probs`` list; both fall back to
    ``score_key`` if those aren't present.
    """
    def uncertainty(it: dict) -> float:
        if strategy == "margin" and "top1" in it and "top2" in it:
            return margin_confidence(it["top1"], it["top2"])
        if strategy == "entropy" and "probs" in it:
            return entropy(it["probs"])
        return least_confidence(it.get(score_key, 1.0))

    return sorted(items, key=uncertainty, reverse=True)


def select_batch(
    items: Sequence[dict],
    k: int,
    *,
    score_key: str = "confidence",
    strategy: str = "least_confidence",
    diversity_key: Optional[str] = None,
) -> list[dict]:
    """Pick the ``k`` most-valuable items to label.

    With ``diversity_key`` (e.g. ``"drawing_id"`` or ``"project_id"``), selection
    round-robins across groups so the batch isn't 50 near-identical crops from one
    sheet — it spreads the labeling budget for better coverage.
    """
    if k <= 0:
        return []
    ranked = uncertainty_rank(items, score_key=score_key, strategy=strategy)
    if not diversity_key:
        return ranked[:k]

    # Round-robin across groups, each group already in uncertainty order.
    groups: dict = {}
    for it in ranked:
        groups.setdefault(it.get(diversity_key), []).append(it)
    queues = list(groups.values())

    picked: list[dict] = []
    i = 0
    while len(picked) < k and any(queues):
        q = queues[i % len(queues)]
        if q:
            picked.append(q.pop(0))
        i += 1
        if i % len(queues) == 0:
            queues = [q for q in queues if q]  # drop emptied groups
    return picked


def rank_drawings_for_review(
    drawings: Sequence[dict],
    *,
    w_uncertainty: float = 1.0,
    w_disagreement: float = 1.5,
) -> list[dict]:
    """Prioritize whole drawings for re-labeling by a combined priority score.

    Each drawing dict: ``{"drawing_id", "mean_confidence", "n_detections",
    "n_rejections"}``. Priority rewards low model confidence (uncertainty) and
    high human rejection rate (disagreement) — the sheets the model most needs
    labeled data on. Returns the list with a ``priority`` field, highest first.
    """
    scored = []
    for d in drawings:
        n = max(1, int(d.get("n_detections", 0)))
        uncertainty = 1.0 - float(d.get("mean_confidence", 1.0))
        disagreement = float(d.get("n_rejections", 0)) / n
        priority = w_uncertainty * uncertainty + w_disagreement * disagreement
        scored.append({**d, "priority": round(priority, 4)})
    return sorted(scored, key=lambda d: d["priority"], reverse=True)
