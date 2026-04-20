from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session
import schemas
import models
from auth import get_current_user
from database import get_db
import json
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/takeoff", tags=["Takeoff & AI"])


# ── NEW: Real AI analyze endpoint ────────────────────────────────
@router.post("/drawings/{drawing_id}/analyze")
async def analyze_drawing(
    drawing_id: int,
    background_tasks: BackgroundTasks,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Trigger real AI analysis on an uploaded drawing.
    Runs YOLOv8-seg in background, saves result to TakeoffResult table.
    Frontend polls /drawings/{id}/results to get the output.

    Integration: Called automatically after a drawing is uploaded,
    OR manually by clicking "Re-run AI" in the Takeoff.jsx header.
    """
    drawing = db.query(models.Drawing).join(models.Project).filter(
        models.Drawing.id == drawing_id,
        models.Project.organization_id == current_user.organization_id
    ).first()

    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")

    # Mark as processing immediately so frontend shows spinner
    drawing.processing_status = models.ProcessingStatus.PROCESSING
    db.commit()

    # Run AI in background — response returns immediately
    background_tasks.add_task(_run_ai_analysis, drawing_id, drawing.file_path, db)

    return {
        "status": "processing",
        "drawing_id": drawing_id,
        "message": "AI analysis started. Poll /results for output."
    }


async def _run_ai_analysis(drawing_id: int, file_path: str, db: Session):
    """Background task: run YOLOv8 + spatial reasoning, save to DB."""
    from dataclasses import asdict

    try:
        # Import AI engine (loaded once at server startup)
        from server import ai_engine
        from ai.spatial_reasoning import enrich_takeoff_result

        logger.info(f"[AI] Starting analysis: drawing_id={drawing_id}")

        # Step 1: YOLOv8 inference
        analysis = ai_engine.analyze(file_path, drawing_id)

        # Step 2: Spatial reasoning layer (room graph, quantities, scale)
        raw_detection = {
            "rooms":   analysis.rooms,
            "walls":   analysis.walls,
            "doors":   analysis.doors,
            "windows": analysis.windows,
            "summary": analysis.summary,
        }
        enriched = enrich_takeoff_result(json.dumps(raw_detection), file_path)

        # Step 3: Save to database
        db_result = models.TakeoffResult(
            drawing_id=drawing_id,
            detection_data=json.dumps(enriched["detection"]),
            quantities_data=json.dumps(enriched["quantities"]),
            confidence_scores=json.dumps({"avg": analysis.confidence_avg}),
            processing_time_ms=analysis.processing_time_ms,
            ai_model_version=analysis.ai_model_version,
        )
        db.add(db_result)

        # Step 4: Mark drawing as completed
        drawing = db.query(models.Drawing).filter(
            models.Drawing.id == drawing_id
        ).first()
        if drawing:
            drawing.processing_status = models.ProcessingStatus.COMPLETED
            drawing.processed_at = datetime.now(timezone.utc)

        db.commit()
        db.refresh(db_result)
        logger.info(f"[AI] Done: drawing_id={drawing_id} | "
                    f"{analysis.processing_time_ms}ms | "
                    f"conf={analysis.confidence_avg:.2f}")

    except Exception as e:
        logger.error(f"[AI] Failed: drawing_id={drawing_id} | {e}")
        drawing = db.query(models.Drawing).filter(
            models.Drawing.id == drawing_id
        ).first()
        if drawing:
            drawing.processing_status = models.ProcessingStatus.FAILED
            db.commit()


# ── Existing routes (unchanged) ───────────────────────────────────

@router.post("/drawings/{drawing_id}/results", response_model=schemas.TakeoffResult)
async def save_detection_results(
    drawing_id: int,
    result_data: schemas.TakeoffResultCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    drawing = db.query(models.Drawing).join(models.Project).filter(
        models.Drawing.id == drawing_id,
        models.Project.organization_id == current_user.organization_id
    ).first()
    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")

    db_result = models.TakeoffResult(
        drawing_id=drawing_id,
        detection_data=result_data.detection_data,
        quantities_data=result_data.quantities_data,
        confidence_scores=result_data.confidence_scores,
        processing_time_ms=result_data.processing_time_ms,
        ai_model_version="yolov8m-seg-v1.0"
    )
    db.add(db_result)
    drawing.processing_status = models.ProcessingStatus.COMPLETED
    drawing.processed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(db_result)
    return db_result


@router.get("/drawings/{drawing_id}/results")
async def get_detection_results(
    drawing_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    drawing = db.query(models.Drawing).join(models.Project).filter(
        models.Drawing.id == drawing_id,
        models.Project.organization_id == current_user.organization_id
    ).first()
    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")

    result = db.query(models.TakeoffResult).filter(
        models.TakeoffResult.drawing_id == drawing_id
    ).order_by(models.TakeoffResult.created_at.desc()).first()

    if not result:
        # Also return the current processing status so frontend can show spinner
        return {
            "message": "No AI results yet",
            "drawing_id": drawing_id,
            "processing_status": drawing.processing_status.value
        }
    return result


@router.get("/projects/{project_id}/results")
async def get_project_results(
    project_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    project = db.query(models.Project).filter(
        models.Project.id == project_id,
        models.Project.organization_id == current_user.organization_id
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    drawings = db.query(models.Drawing).filter(
        models.Drawing.project_id == project_id
    ).all()

    results = []
    for drawing in drawings:
        result = db.query(models.TakeoffResult).filter(
            models.TakeoffResult.drawing_id == drawing.id
        ).order_by(models.TakeoffResult.created_at.desc()).first()
        if result:
            results.append({"drawing": drawing, "result": result})

    return results
