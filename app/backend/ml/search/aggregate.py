"""
Pattern/count search aggregation (Togal-style "find all like this → 42").

Togal's signature move: select one instance of a symbol/condition and instantly
get *every* similar instance across the sheet set, **with a count**. The existing
text/image endpoints (`routes/ai_routes.py`) return a fixed top-K; counting needs
the opposite — every match above a *similarity threshold*, grouped and tallied.

This module is the pure aggregation half (no DB, no CLIP): convert a similarity
threshold to a cosine-distance cutoff, filter matches, and group+count them by
drawing. The pgvector query that produces the raw matches lives in
`clip_embeddings.search_embeddings_threshold`; the endpoint composes the two.
"""

from __future__ import annotations

from typing import Optional, Sequence


def similarity_to_max_distance(min_similarity: float) -> float:
    """Cosine *similarity* threshold (0..1) → max cosine *distance* (pgvector uses distance).

    similarity = 1 - distance, so a 0.9 similarity floor is a 0.1 distance ceiling.
    """
    if not 0.0 <= min_similarity <= 1.0:
        raise ValueError("min_similarity must be in [0, 1]")
    return 1.0 - min_similarity


def filter_by_similarity(results: Sequence[dict], min_similarity: float,
                         *, key: str = "similarity") -> list[dict]:
    """Keep matches whose similarity clears the threshold, highest first."""
    kept = [r for r in results if r.get(key, 0.0) >= min_similarity]
    return sorted(kept, key=lambda r: r.get(key, 0.0), reverse=True)


def count_and_group(
    results: Sequence[dict],
    *,
    min_similarity: float = 0.0,
    exclude_drawing_id: Optional[int] = None,
    max_matches: Optional[int] = None,
) -> dict:
    """Filter, group-by-drawing, and count similarity matches.

    ``results``: dicts with at least ``drawing_id`` and ``similarity``.
    Returns ``{total, per_drawing: [{drawing_id, count}], matches: [...]}`` where
    ``total`` is the full count above threshold and ``matches`` is the (optionally
    capped) location list for rendering. ``exclude_drawing_id`` drops the source
    sheet's own reference instance if desired.
    """
    kept = filter_by_similarity(results, min_similarity)
    if exclude_drawing_id is not None:
        kept = [r for r in kept if r.get("drawing_id") != exclude_drawing_id]

    per: dict = {}
    for r in kept:
        d = r.get("drawing_id")
        per[d] = per.get(d, 0) + 1

    per_drawing = [{"drawing_id": d, "count": c}
                   for d, c in sorted(per.items(), key=lambda kv: (-kv[1], kv[0]))]
    matches = kept if max_matches is None else kept[:max_matches]
    return {"total": len(kept), "per_drawing": per_drawing, "matches": matches}
