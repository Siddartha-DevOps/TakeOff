from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session
import schemas
import models
import entitlements
from auth import get_current_user
from database import get_db
from detection_geometry import persist_detection_geometries
from clip_embeddings import index_drawing_embeddings
import json
import os
import tempfile
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/takeoff", tags=["Takeoff & AI"])


def _require_ai_takeoff_entitlement(db: Session, organization_id: int):
    """
    Entitlements — memory/TOGAL_PARITY_REAUDIT.md #18. Shared by both
    endpoints below that can create a TakeoffResult row (entitlements.py's
    usage count *is* "TakeoffResult rows this month", so either one
    bypassing the check would silently let usage exceed the plan limit).
    """
    allowed, snapshot = entitlements.check_entitlement(db, organization_id, "ai_takeoff")
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "message": f"Monthly AI takeoff limit reached for the {snapshot['plan_label']} plan "
                           f"({snapshot['ai_takeoffs']['used']}/{snapshot['ai_takeoffs']['limit']}). Upgrade to run more takeoffs.",
                "billing": snapshot,
            },
        )


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

    _require_ai_takeoff_entitlement(db, current_user.organization_id)

    # Mark as processing immediately so frontend shows spinner
    drawing.processing_status = models.ProcessingStatus.PROCESSING
    db.commit()

    # Real async queue (celery_app.py) is the primary path — CLAUDE.md
    # guardrail #3: long work is a job, not in-request work. Only falls
    # back to FastAPI's in-process BackgroundTasks (same failure mode as
    # before this change, now an explicit degraded mode instead of the
    # silent default) if enqueueing itself fails — i.e. the broker
    # (Redis) is unreachable. A successfully enqueued task with no worker
    # currently running to consume it is a deployment/ops concern, not
    # something this request can detect or should paper over — that's
    # true of every queue system, not specific to Celery.
    async_mode = "celery"
    try:
        from celery_app import run_ai_analysis_task
        run_ai_analysis_task.delay(drawing_id, drawing.file_path, drawing.page_number)
    except Exception as e:
        logger.warning(f"[AI] Celery broker unavailable, falling back to in-process background task: {e}")
        async_mode = "in_process_fallback"
        background_tasks.add_task(_run_ai_analysis, drawing_id, drawing.file_path, db, drawing.page_number)

    return {
        "status": "processing",
        "drawing_id": drawing_id,
        "async_mode": async_mode,
        "message": "AI analysis started. Poll /results for output."
    }


async def _run_ai_analysis(drawing_id: int, file_path: str, db: Session, page_number: int = 0):
    """Background task: run YOLOv8 + spatial reasoning, save to DB."""
    from dataclasses import asdict

    try:
        # Import AI engine (loaded once at server startup)
        from server import ai_engine
        from ai.spatial_reasoning import enrich_takeoff_result
        import storage

        logger.info(f"[AI] Starting analysis: drawing_id={drawing_id} page={page_number}")

        # file_path may be an object-storage URI (memory/TOGAL_PARITY_REAUDIT.md
        # #12) — resolve_local_path() downloads it to a temp file for the
        # duration of inference/OCR, transparently, and is a no-op for the
        # (still-supported) local-disk case.
        with storage.resolve_local_path(file_path) as local_path:
            # Rasterize the specific page this Drawing represents. A
            # multi-page plan-set upload (memory/TOGAL_PARITY_REAUDIT.md
            # #13) splits into one Drawing per page sharing one file_path —
            # page_number is what picks the right page out of it. This also
            # fixes a pre-existing bug: both YOLO inference and OCR-based
            # scale detection expect a raster image, but were previously
            # handed the raw file path directly, which for a PDF meant
            # cv2.imread() silently returned None (OCR just no-op'd; a real
            # YOLO model would have errored) — rasterizing once here, up
            # front, makes both actually work for PDF uploads, not just images.
            raster_path, raster_img = local_path, None
            try:
                import cv2
                from ai.preprocessing import load_drawing
                raster_img = load_drawing(local_path, page_number=page_number)
                fd, raster_path = tempfile.mkstemp(suffix=".png")
                os.close(fd)
                cv2.imwrite(raster_path, raster_img)
            except ImportError:
                pass  # heavy stack unavailable — fall back to the raw path, same as before this change

            try:
                # Step 1: YOLOv8 inference
                analysis = ai_engine.analyze(raster_path, drawing_id)

                # Step 2: Spatial reasoning layer (room graph, quantities, scale)
                raw_detection = {
                    "rooms":   analysis.rooms,
                    "walls":   analysis.walls,
                    "doors":   analysis.doors,
                    "windows": analysis.windows,
                    "summary": analysis.summary,
                }
                enriched = enrich_takeoff_result(json.dumps(raw_detection), raster_path)
            finally:
                if raster_path != local_path and os.path.exists(raster_path):
                    os.remove(raster_path)

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

            # Plan-set title-block naming (memory/TOGAL_PARITY_REAUDIT.md
            # #13) — best-effort; only overwrites sheet_name if it's still
            # the numbered placeholder ingest_plan_set() gave it, never a
            # name the uploader (or a prior OCR pass) already set.
            if raster_img is not None:
                try:
                    from ai.title_block_ocr import identify_sheet
                    identity = identify_sheet(raster_img, page_index=page_number)
                    if identity["sheet_number"]:
                        drawing.sheet_number = identity["sheet_number"]
                    if identity["discipline"]:
                        drawing.discipline = identity["discipline"]
                    if drawing.sheet_name in (None, f"Page {page_number + 1}"):
                        drawing.sheet_name = identity["sheet_title"]
                except Exception as ocr_err:
                    logger.warning(f"[AI] Title-block OCR failed for drawing_id={drawing_id}: {ocr_err}")

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


# ── Vector AUTODETECT (exact Area/Line/Count, no model weights) ───
# Complements analyze_drawing above: that path runs YOLOv8-seg (needs trained
# weights) on a rasterized page; this path reads the PDF's native vector
# geometry and measures it exactly, so it works today with no weights on any
# vector PDF. The frontend calls this first and only falls back to the raster
# AI path (or the mock) when a sheet has no vector geometry.

_FRACTION_SCALE_RATIOS = {
    (3, 1): 4, (1, 1): 12, (3, 4): 16, (1, 2): 24,
    (3, 8): 32, (1, 4): 48, (3, 16): 64, (1, 8): 96,
    (3, 32): 128, (1, 16): 192,
}


def _parse_scale_ratio(scale_text):
    """Best-effort parse of a stored scale string (e.g. '1/8\"=1'-0\"') to a ratio."""
    if not scale_text:
        return None
    import re
    m = re.search(r"(\d+)\s*/\s*(\d+)", str(scale_text))
    if m:
        return float(_FRACTION_SCALE_RATIOS.get((int(m.group(1)), int(m.group(2))), 0)) or None
    m = re.search(r'1\s*["”]?\s*=\s*(\d+)\s*[\'’]', str(scale_text))
    if m:
        return float(m.group(1)) * 12.0
    return None


def _scale_ratio_for(drawing, override=None):
    """Resolve the scale ratio: explicit override → calibrated → stored → default 96."""
    return (
        override
        or getattr(drawing, "scale_ratio", None)
        or _parse_scale_ratio(getattr(drawing, "scale", None))
        or _parse_scale_ratio(getattr(drawing, "ocr_scale_text", None))
        or 96.0
    )


@router.post("/drawings/{drawing_id}/autodetect")
async def autodetect_drawing(
    drawing_id: int,
    scale_ratio: float = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """One-click AUTODETECT — exact Area/Line/Count from vector geometry.

    Measures the drawing's native PDF vector geometry (no model weights) and
    returns Togal's three primitives plus per-space GeoJSON for the canvas
    overlay and per-type symbol counts. Persisted to TakeoffResult so the
    Quantities panel and export read it. Returns ``is_vector: false`` for
    scanned sheets (use /analyze for those)."""
    drawing = db.query(models.Drawing).join(models.Project).filter(
        models.Drawing.id == drawing_id,
        models.Project.organization_id == current_user.organization_id,
    ).first()
    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")

    if (drawing.file_type or "").upper() != "PDF":
        return {"drawing_id": drawing_id, "is_vector": False,
                "message": "Vector AUTODETECT needs a PDF; use /analyze for images."}

    _require_ai_takeoff_entitlement(db, current_user.organization_id)

    ratio = _scale_ratio_for(drawing, scale_ratio)
    page_no = getattr(drawing, "page_number", 0) or 0

    import storage
    from geometry import measure_pdf, autodetect_from_measure, match_symbols
    from geometry.postgis import to_geojson

    try:
        with storage.resolve_local_path(drawing.file_path) as local_path:
            measure = measure_pdf(local_path, ratio, page_no=page_no)
            symbols = None
            if measure is not None:
                try:
                    symbols = match_symbols(local_path, page_no=page_no)
                except Exception as sym_err:
                    logger.warning(f"[autodetect] symbol match failed {drawing_id}: {sym_err}")
    except Exception as exc:
        logger.error(f"[autodetect] drawing_id={drawing_id} failed: {exc}")
        raise HTTPException(status_code=422, detail=f"Could not read PDF geometry: {exc}")

    if measure is None:
        return {"drawing_id": drawing_id, "is_vector": False, "scale_ratio": ratio,
                "message": "No vector geometry on this sheet — use AI detection (/analyze)."}

    for room in measure["rooms"]:
        geom = room.pop("geometry", None)
        room["geojson"] = to_geojson(geom) if geom is not None else None

    result = autodetect_from_measure(measure)
    symbol_counts = symbols.get("symbol_counts", {}) if symbols else {}
    result["symbol_counts"] = symbol_counts
    result["symbol_groups"] = symbols.get("groups", []) if symbols else []
    result["drawing_id"] = drawing_id
    result["status"] = "ok"

    # Persist to TakeoffResult (symbol_counts folded into the JSON blob so no
    # schema change is needed on this branch). Best-effort — never fail the run.
    try:
        detection_data = {
            "rooms": result.get("area", []), "doors": [], "windows": [],
            "summary": result.get("summary", {}), "primitives": result.get("primitives", {}),
            "symbol_counts": symbol_counts, "scale_ratio": ratio, "method": "vector",
        }
        db.add(models.TakeoffResult(
            drawing_id=drawing_id,
            detection_data=json.dumps(detection_data),
            quantities_data=json.dumps(result.get("quantities", [])),
            confidence_scores=json.dumps({"avg": 1.0, "source": "vector"}),
            processing_time_ms=0,
            ai_model_version="vector-geometry-v1",
        ))
        drawing.processing_status = models.ProcessingStatus.COMPLETED
        drawing.processed_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as exc:
        logger.error(f"[autodetect] persist failed {drawing_id}: {exc}")
        db.rollback()

    return result


@router.post("/drawings/{drawing_id}/detect_symbols")
async def detect_symbols_endpoint(
    drawing_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Count symbols (doors/windows/fixtures). Vector PDFs are counted
    geometrically with no weights; scanned sheets use the YOLOv8-seg symbol
    model, which returns needs_weights until trained weights exist."""
    drawing = db.query(models.Drawing).join(models.Project).filter(
        models.Drawing.id == drawing_id,
        models.Project.organization_id == current_user.organization_id,
    ).first()
    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")

    import storage
    page_no = getattr(drawing, "page_number", 0) or 0
    with storage.resolve_local_path(drawing.file_path) as local_path:
        if (drawing.file_type or "").upper() == "PDF":
            try:
                from geometry import match_symbols
                result = match_symbols(local_path, page_no=page_no)
                if result.get("total_symbols", 0) > 0 or result.get("groups"):
                    result["drawing_id"] = drawing_id
                    result["status"] = "ok"
                    return result
            except Exception as exc:
                logger.warning(f"[detect_symbols] vector match failed {drawing_id}: {exc}")
        from ai.detect_symbols import detect_symbols_raster
        result = detect_symbols_raster(local_path, page_no=page_no)
        result["drawing_id"] = drawing_id
        return result


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

    # This is the endpoint the real frontend flow actually calls per
    # takeoff run (Takeoff.jsx's takeoffAPI.saveResults) — the primary
    # enforcement point, not just analyze_drawing's background-job trigger.
    _require_ai_takeoff_entitlement(db, current_user.organization_id)

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
