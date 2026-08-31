from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session
import schemas
import models
import entitlements
from auth import get_current_user
from database import get_db
from detection_geometry import persist_detection_geometries
from clip_embeddings import index_drawing_embeddings
from ai.inference import ModelUnavailableError
from ratelimit import RateLimit
from scale_validation import require_confirmed_scale
from canonical_takeoff import CanonicalAnnotationError, synchronize_corrected_takeoff
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
@router.post("/drawings/{drawing_id}/analyze",
             dependencies=[Depends(RateLimit("ai_analyze", limit=20, window_s=60))])
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

    require_confirmed_scale(drawing)
    _require_ai_takeoff_entitlement(db, current_user.organization_id)

    # Celery is preferred when Redis is configured. Otherwise a database-
    # recoverable single worker persists the job before enqueueing and resumes
    # unfinished rows after restart. Never retain this request's DB session in
    # FastAPI BackgroundTasks.
    try:
        from analysis_jobs import enqueue_analysis
        queued = enqueue_analysis(db, drawing)
    except Exception as exc:
        drawing.processing_status = models.ProcessingStatus.FAILED
        drawing.processing_error = f"Could not enqueue analysis: {exc}"[:2000]
        db.commit()
        raise HTTPException(status_code=503, detail="AI job queue is unavailable; retry after the service recovers")

    return {
        "status": "processing",
        "drawing_id": drawing_id,
        "async_mode": queued["backend"],
        "job_id": queued["job_id"],
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

        # OCR is part of the same persisted job as inference so text search is
        # restart-recoverable too. It is deliberately best-effort: a missing
        # system OCR binary must not prevent room detection from completing.
        drawing_for_ocr = db.query(models.Drawing).filter(
            models.Drawing.id == drawing_id
        ).first()
        if drawing_for_ocr:
            try:
                from ocr_index import index_drawing_text

                text_blocks = index_drawing_text(db, drawing_for_ocr)
                logger.info("[OCR] Indexed %s text blocks for drawing_id=%s", text_blocks, drawing_id)
            except Exception as ocr_index_err:
                db.rollback()
                logger.warning("[OCR] Index failed for drawing_id=%s: %s", drawing_id, ocr_index_err)

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
                # Render's lightweight API image intentionally excludes cv2,
                # but remote Gradio inference still needs a raster image. Use
                # the already-installed PyMuPDF dependency for PDF pages so a
                # scanned/vector PDF is never uploaded to an Image component.
                if str(local_path).lower().endswith(".pdf"):
                    import fitz

                    fd, raster_path = tempfile.mkstemp(suffix=".png")
                    os.close(fd)
                    try:
                        with fitz.open(local_path) as document:
                            if page_number < 0 or page_number >= len(document):
                                raise ValueError(f"PDF page {page_number} is out of range")
                            page = document[page_number]
                            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                            pixmap.save(raster_path)
                    except Exception:
                        if os.path.exists(raster_path):
                            os.remove(raster_path)
                        raise

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
                from scale_validation import is_scale_confirmed

                persisted_drawing = db.query(models.Drawing).filter(
                    models.Drawing.id == drawing_id
                ).first()
                trusted = bool(persisted_drawing and is_scale_confirmed(persisted_drawing))
                plan_dpi = 300.0 if (
                    persisted_drawing and str(persisted_drawing.file_type or "").upper() == "PDF"
                ) else (getattr(persisted_drawing, "scale_dpi", None) if persisted_drawing else None)
                enriched = enrich_takeoff_result(
                    json.dumps(raw_detection), raster_path,
                    scale_ratio=persisted_drawing.scale_ratio if trusted else None,
                    plan_dpi=plan_dpi if trusted else None,
                )
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
            drawing.processing_error = None

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
                db, drawing.project_id, drawing_id, file_path, enriched["detection"],
                page_number=page_number,
            )
            if indexed:
                logger.info(f"[AI] Indexed {indexed} embeddings for AI Search, drawing_id={drawing_id}")
        except Exception as embed_err:
            logger.warning(f"[AI] Embedding index failed for drawing_id={drawing_id}: {embed_err}")

    except ModelUnavailableError as e:
        # No trained raster model installed — do NOT fabricate detections
        # (the old mock path did). Mark failed with a clear, actionable reason;
        # vector PDFs still get real results via the /autodetect path.
        logger.warning(
            f"[AI] Raster model unavailable for drawing_id={drawing_id}: {e} "
            f"Install trained weights or use vector AUTODETECT."
        )
        drawing = db.query(models.Drawing).filter(
            models.Drawing.id == drawing_id
        ).first()
        if drawing:
            drawing.processing_status = models.ProcessingStatus.FAILED
            drawing.processing_error = str(e)[:2000]
            db.commit()
    except Exception as e:
        logger.error(f"[AI] Failed: drawing_id={drawing_id} | {e}")
        drawing = db.query(models.Drawing).filter(
            models.Drawing.id == drawing_id
        ).first()
        if drawing:
            drawing.processing_status = models.ProcessingStatus.FAILED
            drawing.processing_error = str(e)[:2000]
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
    """Return only a persisted, user-confirmed ratio.

    The legacy query override is rejected so callers cannot bypass the
    auditable calibration endpoints.
    """
    ratio = require_confirmed_scale(drawing)
    if override is not None and abs(float(override) - ratio) > 1e-9:
        raise HTTPException(
            status_code=400,
            detail="Set scale through the calibration endpoint before takeoff; ad-hoc overrides are not accepted.",
        )
    return ratio


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

    symbol_counts = symbols.get("symbol_counts", {}) if symbols else {}
    result = autodetect_from_measure(measure, symbol_counts)
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

    # Persist as first-class geometry (CLAUDE.md §2/§5), converting the engine's
    # PDF points -> the 300-DPI raster plan-space that Detection.geom / scale_ratio
    # / the 3D view use (geometry/coords.py). The response above stays in points
    # (the PDF canvas overlays in points); only the stored geometry is scaled.
    # Best-effort — never fail the AUTODETECT run.
    try:
        from geometry.coords import bbox_to_pixels
        det_px = {"rooms": [], "doors": [], "windows": [], "mep": []}
        for room in measure["rooms"]:
            det_px["rooms"].append({
                "id": room["id"],
                "label": room.get("label", "Space"),
                "bbox": bbox_to_pixels(room["bbox"]),
                "area": room.get("area", 0),  # sqft — DPI-independent, unchanged
                "confidence": room.get("confidence", 1.0),
            })
        _sym_layer = {"door": "doors", "window": "windows", "fixture": "mep", "symbol": "mep"}
        for group in (result.get("symbol_groups") or []):
            layer = _sym_layer.get(group.get("symbol_type"), "mep")
            for inst in group.get("instances", []):
                det_px[layer].append({
                    "id": inst["id"],
                    "type": group.get("symbol_type", "symbol"),
                    "bbox": bbox_to_pixels(inst["bbox"]),
                    "confidence": 1.0,
                })
        persist_detection_geometries(db, drawing.project_id, drawing_id, det_px, source="vector")
    except Exception as exc:
        logger.warning(f"[autodetect] geometry persistence failed {drawing_id}: {exc}")
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
            indexed = index_drawing_embeddings(
                db, drawing.project_id, drawing_id, drawing.file_path, detection,
                page_number=drawing.page_number or 0,
            )
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
            "processing_status": drawing.processing_status.value,
            "processing_job_id": drawing.processing_job_id,
            "processing_attempts": drawing.processing_attempts or 0,
            "processing_started_at": drawing.processing_started_at,
            "processing_error": drawing.processing_error,
        }
    return result


@router.get("/drawings/{drawing_id}/annotations")
async def get_annotation_state(
    drawing_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    drawing = db.query(models.Drawing).join(models.Project).filter(
        models.Drawing.id == drawing_id,
        models.Project.organization_id == current_user.organization_id,
    ).first()
    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")
    return {
        "drawing_id": drawing_id,
        "saved": drawing.annotations_data is not None,
        "annotations": json.loads(drawing.annotations_data) if drawing.annotations_data else [],
    }


@router.put("/drawings/{drawing_id}/annotations")
async def save_annotation_state(
    drawing_id: int,
    payload: schemas.AnnotationStateUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    drawing = db.query(models.Drawing).join(models.Project).filter(
        models.Drawing.id == drawing_id,
        models.Project.organization_id == current_user.organization_id,
    ).with_for_update().first()
    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")

    submitted = json.dumps(payload.annotations, separators=(",", ":"))
    if len(submitted.encode("utf-8")) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Annotation document exceeds 5 MiB")
    try:
        projection = synchronize_corrected_takeoff(db, drawing, payload.annotations)
        encoded = json.dumps(projection["annotations"], separators=(",", ":"))
        unchanged = drawing.annotations_data == encoded
        drawing.annotations_data = encoded
        if not unchanged:
            db.add(models.AnnotationRevision(
                drawing_id=drawing_id,
                created_by_id=current_user.id,
                annotations_data=encoded,
                annotation_count=len(projection["annotations"]),
            ))
            db.flush()
            stale_revisions = db.query(models.AnnotationRevision).filter(
                models.AnnotationRevision.drawing_id == drawing_id,
            ).order_by(models.AnnotationRevision.created_at.desc(), models.AnnotationRevision.id.desc()).offset(50).all()
            for stale_revision in stale_revisions:
                db.delete(stale_revision)
        db.commit()
    except CanonicalAnnotationError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise

    # Search is a rebuildable projection. Old rows were removed in the atomic
    # transaction above, so a failed encoder can never return stale geometry.
    search_indexed = False
    try:
        index_drawing_embeddings(
            db, drawing.project_id, drawing.id, drawing.file_path,
            projection["detection"], drawing.page_number or 0,
        )
        search_indexed = True
    except Exception as exc:
        db.rollback()
        logger.warning("Corrected annotation search reindex failed for drawing %s: %s", drawing.id, exc)

    return {
        "drawing_id": drawing_id,
        "saved": True,
        "count": len(projection["annotations"]),
        "active_count": projection["active_count"],
        "unchanged": unchanged,
        "quantities": projection["quantities"],
        "summary": projection["detection"]["summary"],
        "search_indexed": search_indexed,
    }


@router.get("/drawings/{drawing_id}/annotations/history")
async def list_annotation_history(
    drawing_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    drawing = db.query(models.Drawing).join(models.Project).filter(
        models.Drawing.id == drawing_id,
        models.Project.organization_id == current_user.organization_id,
    ).first()
    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")
    revisions = db.query(models.AnnotationRevision).filter(
        models.AnnotationRevision.drawing_id == drawing_id,
    ).order_by(models.AnnotationRevision.created_at.desc()).limit(50).all()
    return [{
        "id": revision.id,
        "annotation_count": revision.annotation_count,
        "created_by_id": revision.created_by_id,
        "created_at": revision.created_at,
    } for revision in revisions]


@router.post("/drawings/{drawing_id}/annotations/history/{revision_id}/restore")
async def restore_annotation_history(
    drawing_id: int,
    revision_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    drawing = db.query(models.Drawing).join(models.Project).filter(
        models.Drawing.id == drawing_id,
        models.Project.organization_id == current_user.organization_id,
    ).with_for_update().first()
    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")
    revision = db.query(models.AnnotationRevision).filter(
        models.AnnotationRevision.id == revision_id,
        models.AnnotationRevision.drawing_id == drawing_id,
    ).first()
    if not revision:
        raise HTTPException(status_code=404, detail="Annotation version not found")
    try:
        projection = synchronize_corrected_takeoff(db, drawing, json.loads(revision.annotations_data))
        encoded = json.dumps(projection["annotations"], separators=(",", ":"))
        drawing.annotations_data = encoded
        db.add(models.AnnotationRevision(
            drawing_id=drawing_id,
            created_by_id=current_user.id,
            annotations_data=encoded,
            annotation_count=len(projection["annotations"]),
        ))
        db.flush()
        stale_revisions = db.query(models.AnnotationRevision).filter(
            models.AnnotationRevision.drawing_id == drawing_id,
        ).order_by(models.AnnotationRevision.created_at.desc(), models.AnnotationRevision.id.desc()).offset(50).all()
        for stale_revision in stale_revisions:
            db.delete(stale_revision)
        db.commit()
    except (CanonicalAnnotationError, json.JSONDecodeError) as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=f"Annotation version is invalid: {exc}") from exc
    except Exception:
        db.rollback()
        raise

    try:
        index_drawing_embeddings(
            db, drawing.project_id, drawing.id, drawing.file_path,
            projection["detection"], drawing.page_number or 0,
        )
    except Exception as exc:
        db.rollback()
        logger.warning("Restored annotation search reindex failed for drawing %s: %s", drawing.id, exc)
    return {
        "drawing_id": drawing_id,
        "restored_from": revision_id,
        "annotations": projection["annotations"],
        "quantities": projection["quantities"],
        "summary": projection["detection"]["summary"],
    }


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
            # Canonical annotation projections preserve viewer plan space
            # (PDF points or raster pixels). Legacy AI/vector rows used the
            # explicit 300-DPI raster space.
            "plan_units_per_inch": (
                72.0
                if drawing.annotations_data is not None
                and str(drawing.file_type or "").upper() == "PDF"
                else (
                    drawing.scale_dpi
                    if drawing.annotations_data is not None
                    else 300.0  # legacy Detection.geom is explicitly stored in 300-DPI plan space
                )
            ),
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
