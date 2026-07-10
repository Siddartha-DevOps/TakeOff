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
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

# These imports assume the backend dir is in PYTHONPATH
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import models
from auth import get_current_user
from database import get_db

router = APIRouter(prefix="/takeoff", tags=["AI Search & Chat"])


# ──────────────────────────────────────────────────────────────
# AI Image Search endpoint
# ──────────────────────────────────────────────────────────────
@router.post("/projects/{project_id}/search/image")
async def ai_image_search(
    project_id: int,
    query_bbox: dict,               # {drawing_id, x1, y1, x2, y2} — user drew a box
    top_k: int = 10,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    AI Image Search: find similar visual regions across all project drawings.

    Args:
        query_bbox: The region the user drew (source drawing + pixel coords).
        top_k:      Number of matches to return.
    """
    project = db.query(models.Project).filter(
        models.Project.id == project_id,
        models.Project.organization_id == current_user.organization_id,
    ).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    source_drawing = db.query(models.Drawing).filter(
        models.Drawing.id == query_bbox.get("drawing_id"),
        models.Drawing.project_id == project_id,
    ).first()

    if not source_drawing:
        raise HTTPException(status_code=404, detail="Source drawing not found")

    try:
        import clip
        import torch
        import numpy as np
        from PIL import Image as PILImage
        from preprocessing import load_drawing

        # Extract query patch
        img = load_drawing(source_drawing.file_path, page_number=0)
        x1, y1 = int(query_bbox["x1"]), int(query_bbox["y1"])
        x2, y2 = int(query_bbox["x2"]), int(query_bbox["y2"])
        patch = img[y1:y2, x1:x2]

        # Encode with CLIP
        device = "cuda" if torch.cuda.is_available() else "cpu"
        clip_model, clip_preprocess = clip.load("ViT-B/32", device=device)

        pil_patch = PILImage.fromarray(patch[:, :, ::-1])  # BGR→RGB
        tensor = clip_preprocess(pil_patch).unsqueeze(0).to(device)

        with torch.no_grad():
            query_emb = clip_model.encode_image(tensor)
            query_emb = query_emb / query_emb.norm(dim=-1, keepdim=True)

        # TODO: Query pgvector index for similar patches
        # This is where you'd do:
        # SELECT * FROM drawing_embeddings
        # ORDER BY embedding <=> $1 LIMIT $2
        # For now return empty — implement after adding pgvector
        return {
            "query_bbox": query_bbox,
            "results": [],
            "message": "Image search index not yet built. Run index_drawing_for_search task.",
        }

    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="CLIP not installed. Run: pip install git+https://github.com/openai/CLIP.git",
        )


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