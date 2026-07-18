"""Tests for pattern/count search aggregation ('find all like this → N')."""

import pytest

from ml.search.aggregate import (
    count_and_group,
    filter_by_similarity,
    similarity_to_max_distance,
)


def test_similarity_to_max_distance():
    assert similarity_to_max_distance(0.9) == pytest.approx(0.1)
    assert similarity_to_max_distance(1.0) == 0.0


def test_similarity_to_max_distance_validates():
    with pytest.raises(ValueError):
        similarity_to_max_distance(1.5)


def test_filter_by_similarity_sorts_desc():
    rows = [{"similarity": 0.7}, {"similarity": 0.95}, {"similarity": 0.6}]
    kept = filter_by_similarity(rows, 0.65)
    assert [r["similarity"] for r in kept] == [0.95, 0.7]


def test_count_and_group_tallies_per_drawing():
    rows = [
        {"drawing_id": 1, "similarity": 0.95},
        {"drawing_id": 1, "similarity": 0.90},
        {"drawing_id": 2, "similarity": 0.88},
        {"drawing_id": 3, "similarity": 0.50},   # below threshold
    ]
    out = count_and_group(rows, min_similarity=0.85)
    assert out["total"] == 3
    assert out["per_drawing"] == [{"drawing_id": 1, "count": 2}, {"drawing_id": 2, "count": 1}]
    assert len(out["matches"]) == 3


def test_count_and_group_excludes_source_drawing():
    rows = [
        {"drawing_id": 1, "similarity": 0.99},   # source reference
        {"drawing_id": 2, "similarity": 0.90},
    ]
    out = count_and_group(rows, min_similarity=0.85, exclude_drawing_id=1)
    assert out["total"] == 1
    assert out["per_drawing"] == [{"drawing_id": 2, "count": 1}]


def test_count_and_group_caps_matches_but_not_total():
    rows = [{"drawing_id": 1, "similarity": 0.9 + i / 1000} for i in range(50)]
    out = count_and_group(rows, min_similarity=0.85, max_matches=10)
    assert out["total"] == 50            # full count preserved
    assert len(out["matches"]) == 10     # location list capped for the UI


def test_count_and_group_empty():
    out = count_and_group([], min_similarity=0.85)
    assert out == {"total": 0, "per_drawing": [], "matches": []}
