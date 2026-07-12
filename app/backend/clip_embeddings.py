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

import os
import sys
from typing import Optional

from geoalchemy2.elements import WKTElement
from sqlalchemy.orm import Session

import models

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


def embed_image_patch(patch_bgr) -> list:
    """patch_bgr: HxWx3 numpy array, BGR (as returned by ai/preprocessing.load_drawing)."""
    import torch
    from PIL import Image as PILImage

    model, preprocess = _load_clip()
    pil = PILImage.fromarray(patch_bgr[:, :, ::-1])  # BGR -> RGB
    tensor = preprocess(pil).unsqueeze(0).to(_clip_device)
    with torch.no_grad():
        emb = model.encode_image(tensor)
        emb = emb / emb.norm(dim=-1, keepdim=True)
    return emb[0].cpu().tolist()


def embed_text(query: str) -> list:
    """CLIP's image and text encoders share one embedding space, so a text
    query searches the same DrawingEmbedding rows an image-patch query does."""
    import torch
    import clip as clip_lib

    model, _ = _load_clip()
    tokens = clip_lib.tokenize([query]).to(_clip_device)
    with torch.no_grad():
        emb = model.encode_text(tokens)
        emb = emb / emb.norm(dim=-1, keepdim=True)
    return emb[0].cpu().tolist()


def _bbox_to_wkt_polygon(bbox) -> WKTElement:
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

    Returns 0 (not an error) if CLIP isn't installed — callers already
    treat this as best-effort, same as persist_detection_geometries.
    """
    if not clip_available():
        return 0

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
        x1, y1, x2, y2 = [int(v) for v in bbox]
        x1, y1 = max(x1, 0), max(y1, 0)
        patch = img[y1:max(y2, y1 + 1), x1:max(x2, x1 + 1)]
        if patch.size == 0:
            continue
        embedding = embed_image_patch(patch)
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

    q = db.query(
        models.DrawingEmbedding,
        models.DrawingEmbedding.embedding.cosine_distance(query_embedding).label("distance"),
        func.ST_AsGeoJSON(models.DrawingEmbedding.geom).label("geojson"),
    ).filter(models.DrawingEmbedding.project_id == project_id)
    if exclude_drawing_id is not None:
        q = q.filter(models.DrawingEmbedding.drawing_id != exclude_drawing_id)
    return q.order_by("distance").limit(top_k).all()
