from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session
import schemas
import models
from auth import get_current_user
from database import get_db
from detection_geometry import persist_detection_geometries
from clip_embeddings import index_drawing_embeddings
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
        import storage

        logger.info(f"[AI] Starting analysis: drawing_id={drawing_id}")

        # file_path may be an object-storage URI (memory/TOGAL_PARITY_REAUDIT.md
        # #12) — resolve_local_path() downloads it to a temp file for the
        # duration of inference/OCR, transparently, and is a no-op for the
        # (still-supported) local-disk case.
        with storage.resolve_local_path(file_path) as local_path:
            # Step 1: YOLOv8 inference
            analysis = ai_engine.analyze(local_path, drawing_id)

            # Step 2: Spatial reasoning layer (room graph, quantities, scale)
            raw_detection = {
                "rooms":   analysis.rooms,
                "walls":   analysis.walls,
                "doors":   analysis.doors,
                "windows": analysis.windows,
                "summary": analysis.summary,
            }
            enriched = enrich_takeoff_result(json.dumps(raw_detection), local_path)

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

        # Geometry is first-class (CLAUDE.md §2/§5) — mirror the same
        # detections into the PostGIS-backed Detection/Measurement tables,
        # not just the JSON blob above. Best-effort: a failure here shouldn't
        # take down the primary TakeoffResult save.
        try:
            created = persist_detection_geometries(
                db, drawing.project_id, drawing_id, enriched["detection"], source="ai"
            )
            logger.info(f"[AI] Persisted {created} Detection/Measurement rows for drawing_id={drawing_id}")
        except Exception as geo_err:
            logger.warning(f"[AI] Geometry persistence failed for drawing_id={drawing_id}: {geo_err}")

        # AI Search index (memory/TOGAL_PARITY_REAUDIT.md #7) — build CLIP
        # patch embeddings on ingest. No-ops (returns 0) if CLIP isn't
        # installed; best-effort like the geometry persistence above.
        try:
            indexed = index_drawing_embeddings(
                db, drawing.project_id, drawing_id, file_path, enriched["detection"]
            )
            if indexed:
                logger.info(f"[AI] Indexed {indexed} embeddings for AI Search, drawing_id={drawing_id}")
        except Exception as embed_err:
            logger.warning(f"[AI] Embedding index failed for drawing_id={drawing_id}: {embed_err}")

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

    # Geometry is first-class (CLAUDE.md §2/§5) — this is the endpoint the
    # frontend actually calls today (Takeoff.jsx's takeoffAPI.saveResults),
    # so it's the live write path for the PostGIS Detection/Measurement
    # tables, not just the JSON blob above. Best-effort: a malformed/partial
    # detection_data payload shouldn't break saving the primary result.
    try:
        detection = json.loads(result_data.detection_data)
    except json.JSONDecodeError as parse_err:
        logger.warning(f"Malformed detection_data for drawing_id={drawing_id}: {parse_err}")
        detection = None

    if detection is not None:
        try:
            created = persist_detection_geometries(db, drawing.project_id, drawing_id, detection, source="ai")
            logger.info(f"Persisted {created} Detection/Measurement rows for drawing_id={drawing_id}")
        except Exception as geo_err:
            logger.warning(f"Geometry persistence failed for drawing_id={drawing_id}: {geo_err}")

        # AI Search index (memory/TOGAL_PARITY_REAUDIT.md #7) — same
        # best-effort rule as geometry persistence above.
        try:
            indexed = index_drawing_embeddings(db, drawing.project_id, drawing_id, drawing.file_path, detection)
            if indexed:
                logger.info(f"Indexed {indexed} embeddings for AI Search, drawing_id={drawing_id}")
        except Exception as embed_err:
            logger.warning(f"Embedding index failed for drawing_id={drawing_id}: {embed_err}")

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


@router.get("/drawings/{drawing_id}/detections")
async def list_drawing_detections(
    drawing_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    The PostGIS-backed counterpart to GET /drawings/{id}/results: real
    geometry (as GeoJSON) instead of the JSON-blob detection_data field.
    """
    drawing = db.query(models.Drawing).join(models.Project).filter(
        models.Drawing.id == drawing_id,
        models.Project.organization_id == current_user.organization_id
    ).first()
    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")

    from sqlalchemy import func
    rows = db.query(
        models.Detection,
        func.ST_AsGeoJSON(models.Detection.geom).label("geojson"),
    ).filter(models.Detection.drawing_id == drawing_id).all()

    return [
        {
            "id": det.id,
            "annotation_id": det.annotation_id,
            "annotation_type": det.annotation_type,
            "class_label": det.class_label,
            "confidence": det.confidence,
            "source": det.source,
            "condition_id": det.condition_id,
            "geometry": json.loads(geojson),
        }
        for det, geojson in rows
    ]


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
