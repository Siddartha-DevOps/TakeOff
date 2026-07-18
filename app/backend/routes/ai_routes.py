"""
TakeOff.ai — AI Search + Chat routes.

Was previously unmounted (memory/TOGAL_PARITY_REAUDIT.md #3/#6: "two
conflicting route files... server.py only mounts takeoff_routes, so CLIP
image search and real Claude chat are never reachable"). This file used to
also define POST /drawings/{id}/analyze, duplicating takeoff_routes.py's
(Celery-based vs. the synchronous path takeoff_routes.py actually uses,
now wired to PostGIS persistence — see detection_geometry.py). That
duplicate is why this router couldn't be mounted alongside takeoff_routes.py
before: FastAPI would silently let whichever router registered first shadow
the other's identical route. It's removed here — takeoff_routes.py's
/analyze is the one real path — so only image search and chat remain,
which don't collide with anything.
"""

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

# These imports assume the backend dir is in PYTHONPATH
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import models
from auth import get_current_user
from database import get_db
from clip_embeddings import (
    clip_available,
    embed_image_patch,
    embed_text,
    embedding_for_detection,
    search_embeddings,
    search_embeddings_threshold,
)
from ml.search import count_and_group

router = APIRouter(prefix="/takeoff", tags=["AI Search & Chat"])

CLIP_UNAVAILABLE_DETAIL = (
    "AI Search isn't available yet — CLIP model dependencies aren't installed "
    "on the server (app/requirements.txt's torch + CLIP, kept out of the base "
    "API image per CLAUDE.md's separate-GPU-service guardrail)."
)


def _require_project(project_id: int, current_user: models.User, db: Session) -> models.Project:
    project = db.query(models.Project).filter(
        models.Project.id == project_id,
        models.Project.organization_id == current_user.organization_id,
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _search_results_to_response(rows) -> list:
    return [
        {
            "detection_id": row.annotation_id,
            "drawing_id": row.drawing_id,
            "label_hint": row.label_hint,
            "similarity": round(1 - distance, 4),  # cosine_distance -> similarity, easier for a UI to show as "94% match"
            "geometry": json.loads(geojson)["coordinates"][0],  # ring -> same shape as frontend Annotation.geometry
        }
        for row, distance, geojson in rows
    ]


# ──────────────────────────────────────────────────────────────
# AI Image / Pattern Search — draw a region, find visually similar
# patches across the project (auto-count/auto-locate a symbol or condition).
# ──────────────────────────────────────────────────────────────
class ImageSearchQuery(BaseModel):
    drawing_id: int
    x1: float
    y1: float
    x2: float
    y2: float
    top_k: int = 10


@router.post("/projects/{project_id}/search/image")
async def ai_image_search(
    project_id: int,
    query: ImageSearchQuery,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Embed the region the user drew and find its nearest neighbors in the
    project's CLIP index (pgvector cosine search). This is also "pattern
    search" — draw one instance of a recurring symbol/condition and this
    returns every visually similar patch across every sheet in the project,
    ready to convert into count/area annotations (see Takeoff.jsx).
    """
    _require_project(project_id, current_user, db)

    source_drawing = db.query(models.Drawing).filter(
        models.Drawing.id == query.drawing_id,
        models.Drawing.project_id == project_id,
    ).first()
    if not source_drawing:
        raise HTTPException(status_code=404, detail="Source drawing not found")

    if not clip_available():
        raise HTTPException(status_code=503, detail=CLIP_UNAVAILABLE_DETAIL)

    ai_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ai")
    sys.path.insert(0, ai_dir)
    from preprocessing import load_drawing

    img = load_drawing(source_drawing.file_path, page_number=0)
    x1, y1, x2, y2 = int(query.x1), int(query.y1), int(query.x2), int(query.y2)
    patch = img[max(y1, 0):max(y2, 1), max(x1, 0):max(x2, 1)]
    if patch.size == 0:
        raise HTTPException(status_code=400, detail="Query region is empty")

    query_embedding = embed_image_patch(patch)
    rows = search_embeddings(db, project_id, query_embedding, top_k=query.top_k)

    return {"query": query.model_dump(), "results": _search_results_to_response(rows)}


# ──────────────────────────────────────────────────────────────
# AI Text Search — "find all outlets", "find all bedrooms"
# ──────────────────────────────────────────────────────────────
class TextSearchQuery(BaseModel):
    query: str
    top_k: int = 10


@router.post("/projects/{project_id}/search/text")
async def ai_text_search(
    project_id: int,
    body: TextSearchQuery,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    CLIP's text and image encoders share one embedding space, so a plain-
    English query searches the exact same DrawingEmbedding index the image/
    pattern search above does — no separate text index needed.
    """
    _require_project(project_id, current_user, db)

    if not clip_available():
        raise HTTPException(status_code=503, detail=CLIP_UNAVAILABLE_DETAIL)

    if not body.query.strip():
        raise HTTPException(status_code=400, detail="query must not be empty")

    query_embedding = embed_text(body.query.strip())
    rows = search_embeddings(db, project_id, query_embedding, top_k=body.top_k)

    return {"query": body.query, "results": _search_results_to_response(rows)}


# ──────────────────────────────────────────────────────────────
# AI Pattern/Count Search — "find all like this → 42". Threshold-based
# retrieval (not fixed top_k) so the COUNT is meaningful, grouped per sheet.
# Reference can be text, a drawn region, or an existing detection's embedding.
# ──────────────────────────────────────────────────────────────
class CountSearchQuery(BaseModel):
    text: Optional[str] = None
    detection_id: Optional[str] = None
    drawing_id: Optional[int] = None
    x1: Optional[float] = None
    y1: Optional[float] = None
    x2: Optional[float] = None
    y2: Optional[float] = None
    min_similarity: float = 0.85
    max_matches: int = 500


@router.post("/projects/{project_id}/search/count")
async def ai_count_search(
    project_id: int,
    body: CountSearchQuery,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Count every instance similar to a reference across the project.

    Reference resolution (in priority order):
      1. ``detection_id`` — reuse that detection's stored embedding (no CLIP needed).
      2. ``drawing_id`` + ``x1..y2`` — embed the drawn region (needs CLIP).
      3. ``text`` — embed the phrase (needs CLIP).
    Returns ``{total, per_drawing, matches}`` — the count Togal surfaces plus
    per-sheet tallies and match locations ready to drop in as count annotations.
    """
    _require_project(project_id, current_user, db)

    if not 0.0 <= body.min_similarity <= 1.0:
        raise HTTPException(status_code=400, detail="min_similarity must be in [0, 1]")

    query_embedding = None
    exclude_drawing_id = None

    if body.detection_id:
        query_embedding = embedding_for_detection(db, project_id, body.detection_id)
        if query_embedding is None:
            raise HTTPException(status_code=404, detail="No indexed embedding for that detection")
    elif body.drawing_id is not None and None not in (body.x1, body.y1, body.x2, body.y2):
        if not clip_available():
            raise HTTPException(status_code=503, detail=CLIP_UNAVAILABLE_DETAIL)
        source = db.query(models.Drawing).filter(
            models.Drawing.id == body.drawing_id,
            models.Drawing.project_id == project_id,
        ).first()
        if not source:
            raise HTTPException(status_code=404, detail="Source drawing not found")
        ai_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ai")
        sys.path.insert(0, ai_dir)
        from preprocessing import load_drawing
        img = load_drawing(source.file_path, page_number=0)
        x1, y1, x2, y2 = int(body.x1), int(body.y1), int(body.x2), int(body.y2)
        patch = img[max(y1, 0):max(y2, 1), max(x1, 0):max(x2, 1)]
        if patch.size == 0:
            raise HTTPException(status_code=400, detail="Query region is empty")
        query_embedding = embed_image_patch(patch)
        exclude_drawing_id = None  # count includes the source sheet's other instances
    elif body.text and body.text.strip():
        if not clip_available():
            raise HTTPException(status_code=503, detail=CLIP_UNAVAILABLE_DETAIL)
        query_embedding = embed_text(body.text.strip())
    else:
        raise HTTPException(status_code=400, detail="Provide detection_id, drawing_id+bbox, or text")

    rows = search_embeddings_threshold(
        db, project_id, query_embedding,
        min_similarity=body.min_similarity, max_results=max(body.max_matches, 1000),
    )
    results = _search_results_to_response(rows)
    grouped = count_and_group(
        results, min_similarity=body.min_similarity,
        exclude_drawing_id=exclude_drawing_id, max_matches=body.max_matches,
    )
    return {"min_similarity": body.min_similarity, **grouped}


# ──────────────────────────────────────────────────────────────
# TakeOff.CHAT (real Claude API, not mock) — RAG over detections,
# conditions, human corrections, and OCR; citations; SOW/RFP/RFI drafting.
# ──────────────────────────────────────────────────────────────
CLAUDE_MODEL = "claude-sonnet-5"


def _build_detection_context(drawing_id: int, db: Session) -> str:
    result = db.query(models.TakeoffResult).filter(
        models.TakeoffResult.drawing_id == drawing_id
    ).order_by(models.TakeoffResult.created_at.desc()).first()
    if not result:
        return ""
    try:
        det = json.loads(result.detection_data)
    except json.JSONDecodeError:
        return ""

    summary = det.get("summary", {})
    quantities = det.get("quantities", [])
    rooms = [{"label": r.get("label"), "area": r.get("area"), "confidence": r.get("confidence")}
             for r in det.get("rooms", [])]

    return f"""Drawing analysis results:
- Rooms detected: {summary.get('rooms', 0)} | Total area: {summary.get('totalArea', 0)} sqft
- Doors detected: {summary.get('doors', 0)}
- Windows detected: {summary.get('windows', 0)}
- MEP symbols: {summary.get('mep', 0)}

Quantities:
{json.dumps(quantities, indent=2)}

Room breakdown:
{json.dumps(rooms, indent=2)}"""


def _build_conditions_context(project_id: int, db: Session) -> str:
    conditions = db.query(models.Condition).filter(models.Condition.project_id == project_id).all()
    if not conditions:
        return ""
    lines = [
        f"- {c.name} ({c.trade}): unit={c.unit}"
        + (f", unit_cost=${c.unit_cost}/{c.unit}" if c.unit_cost else "")
        + (f", waste={c.waste_percent}%" if c.waste_percent else "")
        for c in conditions
    ]
    return "Defined conditions for this project:\n" + "\n".join(lines)


def _build_corrections_context(drawing_id: int, db: Session) -> str:
    """Human-verified accept/reject/relabel events — the flywheel (see
    routes/correction_routes.py). Real ground truth, stronger signal than
    the raw AI detection blob alone."""
    corrections = db.query(models.CorrectionEvent).filter(
        models.CorrectionEvent.drawing_id == drawing_id
    ).order_by(models.CorrectionEvent.created_at.desc()).limit(20).all()
    if not corrections:
        return ""
    lines = []
    for c in corrections:
        before = json.loads(c.before) if c.before else None
        after = json.loads(c.after) if c.after else None
        lines.append(f"- {c.action} on {c.annotation_type} '{c.annotation_id}': {before} -> {after}")
    return "Human-verified corrections on this sheet (trust these over raw detections where they conflict):\n" + "\n".join(lines)


@router.post("/drawings/{drawing_id}/chat")
async def takeoff_chat(
    drawing_id: int,
    body: dict,                     # {message: str, conversation_history: list}
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    TakeOff.CHAT: answer questions about a drawing using Claude, grounded in
    this sheet's AI detections, defined conditions, human corrections, and
    OCR-read scale notation. Also drafts Scope of Work / RFP / RFI documents
    on request. Every drawing-specific answer is expected to cite the sheet
    by name (see the "citations" field in the response).
    """
    drawing = db.query(models.Drawing).join(models.Project).filter(
        models.Drawing.id == drawing_id,
        models.Project.organization_id == current_user.organization_id,
    ).first()

    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")

    citation = drawing.sheet_name or drawing.original_filename

    context_sections = [
        _build_detection_context(drawing_id, db),
        _build_conditions_context(drawing.project_id, db),
        _build_corrections_context(drawing_id, db),
    ]
    if drawing.ocr_scale_text:
        context_sections.append(f'OCR-read scale notation: "{drawing.ocr_scale_text}"')
    context = "\n\n".join(s for s in context_sections if s)

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not configured")

    import httpx

    system_prompt = f"""You are TakeOff.CHAT, TakeOff.ai's assistant for construction estimators.

Sheet: {citation}
Scale: {drawing.scale or 'unknown'}
File type: {drawing.file_type}

{context or "No AI detections, conditions, or corrections recorded for this sheet yet."}

Answer using only the data above — never invent quantities, rooms, or counts
that aren't in it. If the data doesn't cover what's asked, say so instead of
guessing. When you use a number, name, or fact from the data above, cite it
by referring to "{citation}".

You can also draft standard construction documents when asked:
- Scope of Work (SOW): organize by trade/condition, one line item per
  condition with quantity, unit, and a one-sentence work description.
- Request for Proposal (RFP): SOW plus bid instructions — a due-date
  placeholder, submission format, and a unit-price bid schedule table using
  the defined conditions and their units.
- Request for Information (RFI): numbered, specific questions about
  anything ambiguous, missing, or conflicting in the data above — don't
  guess at intent, ask.

Keep answers concise and actionable. End every answer that uses
drawing-specific data with a line: "Source: {citation}"."""

    messages = body.get("conversation_history", [])
    messages.append({"role": "user", "content": body.get("message", "")})

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": CLAUDE_MODEL,
                "max_tokens": 1024,
                "system": system_prompt,
                "messages": messages,
            },
        )

    if response.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Claude API error: {response.text}")

    data = response.json()
    reply = data["content"][0]["text"]

    return {
        "answer": reply,
        "drawing_id": drawing_id,
        "citations": [citation],
        "model": CLAUDE_MODEL,
    }