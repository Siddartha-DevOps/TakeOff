"""AI Search 'lite' embedding backend — makes text search + count live without CLIP.

Pure-Python; no DB, torch, or numpy. Verifies the feature-hash embedding puts a
query near the labels it names so pgvector cosine search returns the right rows.
"""

import math

from clip_embeddings import (
    EMBEDDING_DIM,
    embed_label,
    embed_text,
    embeddings_backend,
    _lite_text_vector,
    _tokens,
)


def _cos(a, b):
    return sum(x * y for x, y in zip(a, b))


def test_backend_reports_lite_without_clip():
    # No torch/clip in the base image -> lite backend (still fully functional).
    assert embeddings_backend() == "lite"


def test_embedding_is_512d_and_unit_norm():
    v = embed_text("find all doors")
    assert len(v) == EMBEDDING_DIM
    assert math.isclose(math.sqrt(sum(x * x for x in v)), 1.0, abs_tol=1e-9)


def test_stopwords_are_stripped():
    assert _tokens("find all the doors on level 2") == ["doors", "level", "2"]


def test_query_matches_named_label_best():
    q = embed_text("find all doors")
    door = _cos(q, embed_label("Door"))
    assert door > 0.3
    assert door > _cos(q, embed_label("Window"))
    assert door > _cos(q, embed_label("Space"))


def test_fuzzy_singular_plural_match():
    # char-3-gram overlap makes plural/singular and case differences match
    assert _cos(embed_text("outlet"), embed_label("Outlets")) > 0.3
    assert _cos(embed_text("bedrooms"), embed_label("Bedroom")) > 0.3


def test_unrelated_terms_do_not_match():
    assert _cos(embed_text("door"), embed_label("Window")) < 0.2


def test_empty_text_is_zero_vector():
    assert all(x == 0.0 for x in _lite_text_vector(""))


def test_deterministic():
    assert embed_text("find all doors") == embed_text("find all doors")


def test_image_patch_falls_back_to_label_without_clip():
    # No pixels model -> anchors on the label so pattern search still works.
    from clip_embeddings import embed_image_patch
    assert embed_image_patch(None, label="Door") == embed_label("Door")
    assert embed_image_patch(None, label=None) == [0.0] * EMBEDDING_DIM
