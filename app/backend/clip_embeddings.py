"""
TakeOff.ai — CLIP patch embeddings for AI Search (image/text/pattern).
Closes memory/TOGAL_PARITY_REAUDIT.md #7: "CLIP endpoint returns [],
'TODO pgvector'" — see models.DrawingEmbedding for the storage side.

Degrades gracefully exactly like ai/detection_engine.py and
ai/scale_detection.py already do: torch + CLIP (and cv2, via
ai/preprocessing.py) are optional heavy dependencies that live in the
separate app/requirements.txt GPU stack, not backend/requirements.txt,
per CLAUDE.md §2's "heavy ML runs on a separate GPU service" guardrail.
Every public function here either returns cleanly (index_drawing_embeddings
-> 0) or the caller is expected to catch ImportError and respond with a
clear message — never a crash.
"""

from __future__ import annotations

import os
import sys
import hashlib
import math
import re
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:  # keep the pure-embedding functions importable without the DB/ML stack
    from sqlalchemy.orm import Session

EMBEDDING_DIM = 512  # CLIP ViT-B/32
GEOM_SRID = 0        # plan-space pixels, matches Detection/Measurement

_clip_model = None
_clip_preprocess = None
_clip_device = "cpu"

_SYMBOL_DEFAULTS = {"doors": "Door", "windows": "Window", "mep": "Fixture"}


def clip_available() -> bool:
    try:
        import torch  # noqa: F401
        import clip  # noqa: F401
        return True
    except ImportError:
        return False


def _load_clip():
    global _clip_model, _clip_preprocess, _clip_device
    if _clip_model is not None:
        return _clip_model, _clip_preprocess
    import torch
    import clip

    _clip_device = "cuda" if torch.cuda.is_available() else "cpu"
    _clip_model, _clip_preprocess = clip.load("ViT-B/32", device=_clip_device)
    return _clip_model, _clip_preprocess


def embeddings_backend() -> str:
    """Which encoder AI Search uses: real 'clip' when installed, else 'lite'.

    The 'lite' backend is a dependency-free label/text feature-hashing embedding
    (below). It makes text search + count LIVE anywhere — no torch, no weights,
    no network — by matching a query against each detection's class label in a
    shared, normalized vector space that pgvector cosine-searches exactly like
    the CLIP path. CLIP is a drop-in *semantic* upgrade (also enables true
    visual/pattern search on arbitrary regions) when the GPU stack is present.
    """
    return "clip" if clip_available() else "lite"


# ── Lite (dependency-free) embedding backend ──────────────────────────
# Feature hashing (the "hashing trick"): map a string's tokens + char 3-grams
# into a fixed 512-dim L2-normalized vector. Two strings that share tokens/grams
# (e.g. "doors" and "Door") land close in cosine space, so a text query matches
# the labels of the detections it names — fuzzy, deterministic, zero-dependency.
_STOPWORDS = frozenset({
    "find", "all", "the", "a", "an", "show", "me", "of", "with", "every",
    "get", "list", "where", "are", "is", "in", "on", "and", "to", "for", "any",
})


def _tokens(text: str) -> list:
    return [t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if t not in _STOPWORDS]


def _lite_text_vector(text: str, dim: int = EMBEDDING_DIM) -> list:
    vec = [0.0] * dim
    grams: list = []
    for tok in _tokens(text):
        grams.append(tok)                      # whole token
        s = f"#{tok}#"
        for i in range(len(s) - 2):            # char 3-grams (fuzzy: doors ~ door)
            grams.append(s[i:i + 3])
    for g in grams:
        h = int(hashlib.md5(g.encode()).hexdigest(), 16)
        vec[h % dim] += 1.0 if (h >> 8) & 1 else -1.0
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec] if norm > 0 else vec


def embed_label(label: str) -> list:
    """Embedding for a detection's class label — the index side of text search.
    Uses CLIP's text encoder when available (so it shares CLIP's image space),
    otherwise the lite feature-hash vector."""
    return embed_text(label)


def embed_image_patch(patch_bgr, label: Optional[str] = None) -> list:
    """Embed a detection patch. CLIP encodes the pixels; the lite backend
    anchors on the patch's class `label` (label-based search — no pixels needed),
    returning a neutral zero vector only when neither pixels-model nor label
    exist."""
    if clip_available():
        import torch
        from PIL import Image as PILImage

        model, preprocess = _load_clip()
        pil = PILImage.fromarray(patch_bgr[:, :, ::-1])  # BGR -> RGB
        tensor = preprocess(pil).unsqueeze(0).to(_clip_device)
        with torch.no_grad():
            emb = model.encode_image(tensor)
            emb = emb / emb.norm(dim=-1, keepdim=True)
        return emb[0].cpu().tolist()
    return _lite_text_vector(label) if label else [0.0] * EMBEDDING_DIM


def embed_text(query: str) -> list:
    """Embed a text query. CLIP's image and text encoders share one space, so a
    text query searches the same DrawingEmbedding rows an image-patch query does;
    the lite backend matches the query against detection labels."""
    if not clip_available():
        return _lite_text_vector(query)
    import torch
    import clip as clip_lib

    model, _ = _load_clip()
    tokens = clip_lib.tokenize([query]).to(_clip_device)
    with torch.no_grad():
        emb = model.encode_text(tokens)
        emb = emb / emb.norm(dim=-1, keepdim=True)
    return emb[0].cpu().tolist()


def _bbox_to_wkt_polygon(bbox) -> "WKTElement":
    from geoalchemy2.elements import WKTElement
    x1, y1, x2, y2 = bbox
    ring = f"{x1} {y1}, {x2} {y1}, {x2} {y2}, {x1} {y2}, {x1} {y1}"
    return WKTElement(f"POLYGON(({ring}))", srid=GEOM_SRID)


def _symbol_bbox(item: dict) -> list:
    bbox = item.get("bbox")
    if bbox:
        return bbox
    x, y, width = item.get("x", 0), item.get("y", 0), item.get("width", 20)
    return [x - width / 2, y - 10, x + width / 2, y + 10]


def index_drawing_embeddings(
    db: Session,
    project_id: int,
    drawing_id: int,
    file_path: str,
    detection: dict,
) -> int:
    """
    Build CLIP patch embeddings on ingest — one per AI detection (rooms,
    doors, windows, mep), reusing the same bboxes
    detection_geometry.persist_detection_geometries() stores as PostGIS
    geometry, so every embedded patch is also a real Detection row.

    With the lite backend (no CLIP) this indexes by label — no image load
    needed — so search still goes live; with CLIP it embeds the actual pixels.
    """
    import models
    use_clip = clip_available()
    img = None
    if use_clip:
        ai_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai")
        sys.path.insert(0, ai_dir)
        from preprocessing import load_drawing
        img = load_drawing(file_path, page_number=0)

    items = [(r["id"], r.get("label", "Room"), r["bbox"]) for r in (detection.get("rooms") or [])]
    for layer_key, default_label in _SYMBOL_DEFAULTS.items():
        for item in detection.get(layer_key) or []:
            items.append((item["id"], item.get("type", default_label), _symbol_bbox(item)))

    created = 0
    for annotation_id, label, bbox in items:
        if use_clip and img is not None:
            x1, y1, x2, y2 = [int(v) for v in bbox]
            x1, y1 = max(x1, 0), max(y1, 0)
            patch = img[y1:max(y2, y1 + 1), x1:max(x2, x1 + 1)]
            if patch.size == 0:
                continue
            embedding = embed_image_patch(patch, label)
        else:
            embedding = embed_image_patch(None, label)  # lite: label-anchored
        db.add(models.DrawingEmbedding(
            project_id=project_id,
            drawing_id=drawing_id,
            annotation_id=str(annotation_id),
            label_hint=label,
            geom=_bbox_to_wkt_polygon(bbox),
            embedding=embedding,
        ))
        created += 1

    db.commit()
    return created


def index_project_from_detections(db: Session, project_id: int, replace: bool = True) -> int:
    """Backfill DrawingEmbedding rows from a project's existing Detection rows,
    label-anchored, so AI text search + count go live over already-analyzed
    drawings without reprocessing any images (works with the lite or CLIP-text
    backend). Reuses each Detection's PostGIS geom so results carry geometry.

    Returns the number of embeddings written.
    """
    import models
    if replace:
        db.query(models.DrawingEmbedding).filter(
            models.DrawingEmbedding.project_id == project_id
        ).delete()
        db.flush()

    created = 0
    for det in db.query(models.Detection).filter(models.Detection.project_id == project_id).all():
        label = det.class_label or "detection"
        db.add(models.DrawingEmbedding(
            project_id=project_id,
            drawing_id=det.drawing_id,
            annotation_id=det.annotation_id,
            label_hint=label,
            geom=det.geom,
            embedding=embed_label(label),
        ))
        created += 1

    db.commit()
    return created


def search_embeddings(db: Session, project_id: int, query_embedding: list, top_k: int = 10, exclude_drawing_id: Optional[int] = None):
    """
    Cosine-nearest DrawingEmbedding rows in a project, closest first.
    Returns (DrawingEmbedding, distance, geojson) tuples. GeoJSON (not WKT)
    to match routes/takeoff_routes.py's GET /drawings/{id}/detections — a
    GeoJSON Polygon's coordinate ring is already exactly the frontend
    Annotation model's `geometry` shape, so a result converts into a
    count/area annotation with no parsing (see Takeoff.jsx's
    "Add as Count/Area").
    """
    from sqlalchemy import func
    import models

    q = db.query(
        models.DrawingEmbedding,
        models.DrawingEmbedding.embedding.cosine_distance(query_embedding).label("distance"),
        func.ST_AsGeoJSON(models.DrawingEmbedding.geom).label("geojson"),
    ).filter(models.DrawingEmbedding.project_id == project_id)
    if exclude_drawing_id is not None:
        q = q.filter(models.DrawingEmbedding.drawing_id != exclude_drawing_id)
    return q.order_by("distance").limit(top_k).all()


def search_embeddings_threshold(db: Session, project_id: int, query_embedding: list,
                                min_similarity: float = 0.85, max_results: int = 1000,
                                exclude_drawing_id: Optional[int] = None):
    """Every DrawingEmbedding within a similarity threshold (for pattern/COUNT search).

    Unlike search_embeddings' fixed top_k, this returns *all* matches whose cosine
    similarity >= min_similarity (distance <= 1 - min_similarity), closest first,
    capped at max_results. That count is the "there are 42 of these" number Togal
    surfaces. Same (DrawingEmbedding, distance, geojson) tuple shape.
    """
    from sqlalchemy import func

    max_distance = 1.0 - float(min_similarity)
    dist = models.DrawingEmbedding.embedding.cosine_distance(query_embedding)
    q = db.query(
        models.DrawingEmbedding,
        dist.label("distance"),
        func.ST_AsGeoJSON(models.DrawingEmbedding.geom).label("geojson"),
    ).filter(
        models.DrawingEmbedding.project_id == project_id,
        dist <= max_distance,
    )
    if exclude_drawing_id is not None:
        q = q.filter(models.DrawingEmbedding.drawing_id != exclude_drawing_id)
    return q.order_by("distance").limit(max_results).all()


def embedding_for_detection(db: Session, project_id: int, annotation_id: str) -> Optional[list]:
    """The stored CLIP vector for an existing detection, or None.

    Lets "find all like THIS detection" reuse an indexed embedding as the query —
    no CLIP/torch needed at query time, only that the sheet was indexed on ingest.
    """
    row = (
        db.query(models.DrawingEmbedding)
        .filter(
            models.DrawingEmbedding.project_id == project_id,
            models.DrawingEmbedding.annotation_id == annotation_id,
        )
        .first()
    )
    return list(row.embedding) if row is not None else None
