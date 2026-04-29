"""
TakeOff.ai — Real AI Takeoff Routes
Replaces the mock endpoints in takeoff_routes.py.

Drop-in: add to server.py as:
    from routes.ai_routes import router as ai_router
    app.include_router(ai_router, prefix="/api")

The frontend calls /api/takeoff/drawings/{id}/analyze which is unchanged —
only the implementation switches from mock to real AI.
"""

import json
import time
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, status
from sqlalchemy.orm import Session

# These imports assume the backend dir is in PYTHONPATH
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import models
from auth import get_current_user
from database import get_db

router = APIRouter(prefix="/takeoff", tags=["AI Takeoff"])


# ──────────────────────────────────────────────────────────────
# Trigger AI analysis for a drawing (async, non-blocking)
# ──────────────────────────────────────────────────────────────
@router.post("/drawings/{drawing_id}/analyze")
async def analyze_drawing(
    drawing_id: int,
    background_tasks: BackgroundTasks,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Trigger real AI analysis of a drawing.

    Returns immediately with status=processing.
    Frontend polls GET /drawings/{id}/results for completion.
    """
    drawing = db.query(models.Drawing).join(models.Project).filter(
        models.Drawing.id == drawing_id,
        models.Project.organization_id == current_user.organization_id,
    ).first()

    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")

    if drawing.processing_status == models.ProcessingStatus.PROCESSING:
        return {"status": "already_processing", "drawing_id": drawing_id}

    # Update status
    drawing.processing_status = models.ProcessingStatus.PROCESSING
    db.commit()

    # Dispatch to Celery worker (non-blocking)
    background_tasks.add_task(
        _dispatch_ai_task,
        drawing_id=drawing_id,
        file_path=drawing.file_path,
        db_url=os.getenv("DATABASE_URL", ""),
    )

    return {
        "status": "processing",
        "drawing_id": drawing_id,
        "message": "AI analysis started. Poll GET /results for completion.",
    }


async def _dispatch_ai_task(drawing_id: int, file_path: str, db_url: str):
    """
    Dispatch AI task to Celery worker.
    If Celery is not available, run synchronously (for local dev without Redis).
    """
    try:
        from ai_tasks import run_ai_analysis, index_drawing_for_search

        # Fire-and-forget Celery tasks
        task = run_ai_analysis.delay(drawing_id, file_path)
        index_drawing_for_search.delay(drawing_id, file_path)

        import logging
        logging.getLogger(__name__).info(
            f"AI task dispatched: {task.id} for drawing {drawing_id}"
        )

        # Set up Celery result callback to update DB
        _schedule_result_save(task.id, drawing_id)

    except ImportError:
        # Celery not available — run synchronously (dev mode)
        import logging
        logging.getLogger(__name__).warning(
            "Celery not available — running AI synchronously (not for production)"
        )
        await _run_ai_sync(drawing_id, file_path)


async def _run_ai_sync(drawing_id: int, file_path: str):
    """
    Run AI analysis synchronously (development fallback).
    In production, always use Celery workers.
    """
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    def _run():
        # Check if real model exists
        try:
            sys.path.insert(0, os.path.dirname(__file__))
            from detection_engine import BlueprintDetector, model_is_available
            from preprocessing import load_drawing
            from scale_detection import run_ocr_for_scale
        except ImportError:
            return None

        if not model_is_available():
            return None

        img = load_drawing(file_path, page_number=0)
        scale_info = run_ocr_for_scale(img)
        detector = BlueprintDetector()
        return detector.detect(img, scale_info=scale_info)

    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as pool:
        result = await loop.run_in_executor(pool, _run)

    # Save to DB
    from database import SessionLocal
    db = SessionLocal()
    try:
        drawing = db.query(models.Drawing).filter(models.Drawing.id == drawing_id).first()
        if not drawing:
            return

        if result:
            db_result = models.TakeoffResult(
                drawing_id=drawing_id,
                detection_data=json.dumps(result),
                quantities_data=json.dumps(result.get("quantities", [])),
                confidence_scores=json.dumps(_avg_confidence(result)),
                processing_time_ms=result.get("processing_time_ms", 0),
                ai_model_version=result.get("model_version", "yolov8m-v1"),
            )
            db.add(db_result)
            drawing.processing_status = models.ProcessingStatus.COMPLETED
        else:
            # No model yet — use fallback mock
            mock_result = _generate_fallback_result(drawing_id)
            db_result = models.TakeoffResult(
                drawing_id=drawing_id,
                detection_data=json.dumps(mock_result),
                quantities_data=json.dumps(mock_result.get("quantities", [])),
                confidence_scores=json.dumps({"avg": 0.0, "note": "mock — train model first"}),
                processing_time_ms=0,
                ai_model_version="mock_fallback_v0",
            )
            db.add(db_result)
            drawing.processing_status = models.ProcessingStatus.COMPLETED

        drawing.processed_at = datetime.now(timezone.utc)
        db.commit()

    finally:
        db.close()


def _schedule_result_save(celery_task_id: str, drawing_id: int):
    """
    Schedule a follow-up task to save Celery results to DB when done.
    This runs as a separate low-overhead Celery task.
    """
    try:
        from ai_tasks import app as celery_app

        @celery_app.task(name="ai_tasks.save_results")
        def save_results(task_id, drw_id):
            from celery.result import AsyncResult
            result = AsyncResult(task_id)
            result.wait(timeout=180)
            if result.successful():
                _persist_result(drw_id, result.result)
            else:
                _mark_failed(drw_id)

        save_results.apply_async(
            args=[celery_task_id, drawing_id],
            countdown=5,  # check after 5 seconds
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Could not schedule result save: {e}")


def _persist_result(drawing_id: int, result: dict):
    """Save AI result to database."""
    from database import SessionLocal

    db = SessionLocal()
    try:
        drawing = db.query(models.Drawing).filter(models.Drawing.id == drawing_id).first()
        if not drawing:
            return

        # Remove or update existing result
        existing = db.query(models.TakeoffResult).filter(
            models.TakeoffResult.drawing_id == drawing_id
        ).first()

        data = {
            "drawing_id": drawing_id,
            "detection_data": json.dumps(result),
            "quantities_data": json.dumps(result.get("quantities", [])),
            "confidence_scores": json.dumps(_avg_confidence(result)),
            "processing_time_ms": result.get("processing_time_ms", 0),
            "ai_model_version": result.get("model_version", "yolov8m-v1"),
        }

        if existing:
            for k, v in data.items():
                setattr(existing, k, v)
        else:
            db.add(models.TakeoffResult(**data))

        drawing.processing_status = models.ProcessingStatus.COMPLETED
        drawing.processed_at = datetime.now(timezone.utc)
        db.commit()

    finally:
        db.close()


def _mark_failed(drawing_id: int):
    from database import SessionLocal

    db = SessionLocal()
    try:
        drawing = db.query(models.Drawing).filter(models.Drawing.id == drawing_id).first()
        if drawing:
            drawing.processing_status = models.ProcessingStatus.FAILED
            db.commit()
    finally:
        db.close()


def _avg_confidence(result: dict) -> dict:
    """Compute average confidence scores per detection type."""
    def avg(items):
        if not items:
            return 0.0
        return round(sum(i.get("confidence", 0) for i in items) / len(items), 3)

    return {
        "rooms": avg(result.get("rooms", [])),
        "doors": avg(result.get("doors", [])),
        "windows": avg(result.get("windows", [])),
        "mep": avg(result.get("mep", [])),
    }


def _generate_fallback_result(drawing_id: int) -> dict:
    """
    Returns an empty result with clear indication that training is needed.
    This replaces the old mock data — shows real status to users.
    """
    return {
        "rooms": [],
        "doors": [],
        "windows": [],
        "mep": [],
        "summary": {"rooms": 0, "doors": 0, "windows": 0, "totalArea": 0},
        "quantities": [],
        "model_status": "untrained",
        "message": "AI model not trained yet. Run: python training/train.py to train.",
        "processing_time_ms": 0,
    }


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
# TakeOff Chat endpoint (real Claude API, not mock)
# ──────────────────────────────────────────────────────────────
@router.post("/drawings/{drawing_id}/chat")
async def takeoff_chat(
    drawing_id: int,
    body: dict,                     # {message: str, conversation_history: list}
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    TakeOff Chat: answer questions about a drawing using Claude API.
    Context = detection results + OCR text of the drawing.
    """
    drawing = db.query(models.Drawing).join(models.Project).filter(
        models.Drawing.id == drawing_id,
        models.Project.organization_id == current_user.organization_id,
    ).first()

    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")

    # Get detection context
    result = db.query(models.TakeoffResult).filter(
        models.TakeoffResult.drawing_id == drawing_id
    ).order_by(models.TakeoffResult.created_at.desc()).first()

    detection_context = ""
    if result:
        try:
            det = json.loads(result.detection_data)
            summary = det.get("summary", {})
            quantities = det.get("quantities", [])
            detection_context = f"""
Drawing analysis results:
- Rooms detected: {summary.get('rooms', 0)} | Total area: {summary.get('totalArea', 0)} sqft
- Doors detected: {summary.get('doors', 0)}
- Windows detected: {summary.get('windows', 0)}
- MEP symbols: {summary.get('mep', 0)}

Quantities:
{json.dumps(quantities, indent=2)}

Room breakdown:
{json.dumps([{'label': r['label'], 'area': r['area'], 'confidence': r['confidence']} for r in det.get('rooms', [])], indent=2)}
"""
        except (json.JSONDecodeError, KeyError):
            pass

    # Build Claude API request
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not configured")

    import httpx

    system_prompt = f"""You are TakeOff.ai's AI assistant helping construction estimators understand their drawings.

Drawing: {drawing.sheet_name or drawing.original_filename}
Scale: {drawing.scale or 'unknown'}
File: {drawing.file_type}

{detection_context}

Answer questions about quantities, measurements, room types, scope of work, and RFP generation.
Be specific and cite the detection data above. Keep answers concise and actionable for estimators.
When writing scope of work or RFPs, use standard construction industry language."""

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
                "model": "claude-sonnet-4-20250514",
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
        "model": "claude-sonnet-4-20250514",
    }