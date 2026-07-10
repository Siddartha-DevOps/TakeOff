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


# ── Vector-PDF geometry (exact measurement, gap #26) ──────────────
# Common architectural fraction scales -> ratio (real inches per paper inch).
_FRACTION_SCALE_RATIOS = {
    (3, 1): 4, (1, 1): 12, (3, 4): 16, (1, 2): 24,
    (3, 8): 32, (1, 4): 48, (3, 16): 64, (1, 8): 96,
    (3, 32): 128, (1, 16): 192,
}


def _parse_scale_ratio(scale_text: str | None) -> float | None:
    """Best-effort parse of a stored scale string (e.g. '1/8\"=1'-0\"') to a ratio.

    Kept local and dependency-free — ``ai.scale_detection`` imports OpenCV at
    module load, which we must not pull onto a web worker.
    """
    if not scale_text:
        return None
    import re

    m = re.search(r"(\d+)\s*/\s*(\d+)", scale_text)
    if m:
        return float(_FRACTION_SCALE_RATIOS.get((int(m.group(1)), int(m.group(2))), 0)) or None
    m = re.search(r'1\s*["”]?\s*=\s*(\d+)\s*[\'’]', scale_text)  # 1"=20'
    if m:
        return float(m.group(1)) * 12.0
    return None


@router.get("/drawings/{drawing_id}/vector-geometry")
async def get_vector_geometry(
    drawing_id: int,
    scale_ratio: float | None = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Measure a drawing's true vector geometry (exact, DPI-independent).

    Reads native PDF vector linework and returns rooms (as GeoJSON polygons),
    exact areas/perimeters and wall linear feet. Falls back with ``is_vector:
    false`` for scanned/raster sheets, where the AI pipeline should be used.

    ``scale_ratio`` (real inches per paper inch, e.g. 96 for 1/8"=1'-0") may be
    passed explicitly; otherwise it is parsed from the drawing's stored scale,
    defaulting to 96.
    """
    drawing = db.query(models.Drawing).join(models.Project).filter(
        models.Drawing.id == drawing_id,
        models.Project.organization_id == current_user.organization_id,
    ).first()
    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")

    if (drawing.file_type or "").upper() != "PDF":
        return {
            "drawing_id": drawing_id,
            "is_vector": False,
            "message": "Vector geometry is only available for PDF drawings.",
        }

    import os
    if not os.path.exists(drawing.file_path):
        raise HTTPException(status_code=404, detail="File not found on server")

    ratio = scale_ratio or _parse_scale_ratio(drawing.scale) or 96.0

    from geometry import measure_pdf
    from geometry.postgis import to_geojson

    try:
        result = measure_pdf(drawing.file_path, ratio)
    except Exception as exc:  # corrupt/locked PDF — don't 500 the UI
        logger.error(f"[vector] drawing_id={drawing_id} failed: {exc}")
        raise HTTPException(status_code=422, detail=f"Could not read PDF geometry: {exc}")

    if result is None:
        return {
            "drawing_id": drawing_id,
            "is_vector": False,
            "scale_ratio": ratio,
            "message": "No vector geometry on this page — use AI detection (raster).",
        }

    # Replace shapely geometry with JSON-serializable GeoJSON for the response.
    for room in result["rooms"]:
        geom = room.pop("geometry", None)
        room["geojson"] = to_geojson(geom) if geom is not None else None

    result["drawing_id"] = drawing_id
    return result


@router.post("/drawings/{drawing_id}/autodetect")
async def autodetect_drawing(
    drawing_id: int,
    scale_ratio: float | None = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """One-click AUTODETECT — Togal's Area/Line/Count on the real plan.

    Measures the drawing's true vector geometry (exact, no model weights needed)
    and returns the three takeoff primitives — Area (sqft), Line (linear ft) and
    Count (each) — plus per-space polygons (GeoJSON) for canvas overlay and a
    flat trade-quantity list. The result is persisted to ``TakeoffResult`` so the
    Quantities panel and Excel export pick it up.

    Scanned/raster sheets have no vector geometry to measure; they fall back to
    the AI detector, which requires trained weights (see ``ai/detection_engine``
    and ``training/train.py``). Until weights are present the response reports
    ``status: needs_weights`` instead of fabricating numbers.
    """
    drawing = db.query(models.Drawing).join(models.Project).filter(
        models.Drawing.id == drawing_id,
        models.Project.organization_id == current_user.organization_id,
    ).first()
    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")

    ratio = scale_ratio or _parse_scale_ratio(drawing.scale) or 96.0

    # Vector path: exact geometry, no weights.
    if (drawing.file_type or "").upper() == "PDF":
        import os
        if not os.path.exists(drawing.file_path):
            raise HTTPException(status_code=404, detail="File not found on server")

        from geometry import measure_pdf, autodetect_from_measure
        from geometry.postgis import to_geojson

        try:
            measure = measure_pdf(drawing.file_path, ratio)
        except Exception as exc:
            logger.error(f"[autodetect] drawing_id={drawing_id} failed: {exc}")
            raise HTTPException(status_code=422, detail=f"Could not read PDF geometry: {exc}")

        if measure is not None:
            # Serialize shapely geometry to GeoJSON for the overlay/response.
            for room in measure["rooms"]:
                geom = room.pop("geometry", None)
                room["geojson"] = to_geojson(geom) if geom is not None else None

            result = autodetect_from_measure(measure)
            result["drawing_id"] = drawing_id
            result["status"] = "ok"

            # Count symbols (doors/windows/fixtures) from the same vector data.
            symbol_counts = {}
            try:
                from geometry import match_symbols
                symbols = match_symbols(drawing.file_path, page_no=measure.get("page_no", 0))
                symbol_counts = symbols.get("symbol_counts", {})
                result["symbol_counts"] = symbol_counts
                result["symbol_groups"] = symbols.get("groups", [])
            except Exception as exc:  # counting is additive; never fail AUTODETECT
                logger.error(f"[autodetect] symbol match failed for {drawing_id}: {exc}")
                result["symbol_counts"] = {}

            _persist_autodetect(db, drawing, result, ratio, symbol_counts)
            return result

    # Raster / non-vector fallback.
    weights_available = _ai_weights_available()
    drawing.processing_status = (
        models.ProcessingStatus.PROCESSING if weights_available else models.ProcessingStatus.PENDING
    )
    db.commit()

    return {
        "drawing_id": drawing_id,
        "method": "ai" if weights_available else "none",
        "is_vector": False,
        "status": "processing" if weights_available else "needs_weights",
        "scale_ratio": ratio,
        "message": (
            "No vector geometry on this sheet. Running AI detection (trained "
            "weights found) — poll /results."
            if weights_available else
            "This is a raster/scanned sheet with no vector geometry, and no AI "
            "weights are installed. Upload a vector PDF for exact AUTODETECT, or "
            "train/obtain weights (training/train.py or AI_MODELS_BUCKET)."
        ),
    }


def _ai_weights_available() -> bool:
    """Cheap check for trained AI weights, without importing the heavy stack."""
    try:
        from ai.detection_engine import model_is_available
        return bool(model_is_available())
    except Exception:
        return False


def _persist_autodetect(
    db: Session, drawing, result: dict, ratio: float, symbol_counts: dict | None = None
) -> None:
    """Save an AUTODETECT result so Quantities/export/getResults can read it."""
    detection_data = {
        "rooms": result.get("area", []),
        "doors": [],
        "windows": [],
        "summary": result.get("summary", {}),
        "primitives": result.get("primitives", {}),
        "scale_ratio": ratio,
        "method": result.get("method"),
    }
    try:
        db_result = models.TakeoffResult(
            drawing_id=drawing.id,
            detection_data=json.dumps(detection_data),
            quantities_data=json.dumps(result.get("quantities", [])),
            symbol_counts=json.dumps(symbol_counts or {}),
            confidence_scores=json.dumps({"avg": 1.0, "source": "vector"}),
            processing_time_ms=0,
            ai_model_version="vector-geometry-v1",
        )
        db.add(db_result)
        drawing.processing_status = models.ProcessingStatus.COMPLETED
        drawing.processed_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as exc:  # persistence is best-effort; never fail the request
        logger.error(f"[autodetect] persist failed for drawing {drawing.id}: {exc}")
        db.rollback()


@router.post("/drawings/{drawing_id}/detect_symbols")
async def detect_symbols(
    drawing_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Count symbols (doors/windows/fixtures) — Togal's Count primitive.

    Vector PDFs are counted geometrically (exact, no weights) via
    ``geometry.match_symbols``. Scanned/raster sheets use the YOLOv8-seg symbol
    model (``ai.detect_symbols``), which returns ``status: needs_weights`` until
    ``models/symbol_counts/yolov8-seg.pt`` exists. Counts are saved to
    ``TakeoffResult.symbol_counts``.
    """
    drawing = db.query(models.Drawing).join(models.Project).filter(
        models.Drawing.id == drawing_id,
        models.Project.organization_id == current_user.organization_id,
    ).first()
    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")

    import os
    if not os.path.exists(drawing.file_path):
        raise HTTPException(status_code=404, detail="File not found on server")

    is_pdf = (drawing.file_type or "").upper() == "PDF"

    # Vector path first — exact, no weights.
    if is_pdf:
        try:
            from geometry import match_symbols
            result = match_symbols(drawing.file_path)
            if result.get("total_symbols", 0) > 0 or result.get("groups"):
                result["drawing_id"] = drawing_id
                result["status"] = "ok"
                _persist_symbol_counts(db, drawing_id, result.get("symbol_counts", {}))
                return result
        except Exception as exc:
            logger.error(f"[detect_symbols] vector match failed for {drawing_id}: {exc}")

    # Raster fallback — YOLOv8-seg symbol model (needs weights).
    from ai.detect_symbols import detect_symbols_raster
    result = detect_symbols_raster(drawing.file_path)
    result["drawing_id"] = drawing_id
    if result.get("status") == "ok":
        _persist_symbol_counts(db, drawing_id, result.get("symbol_counts", {}))
    return result


def _persist_symbol_counts(db: Session, drawing_id: int, symbol_counts: dict) -> None:
    """Best-effort: attach symbol counts to the drawing's latest TakeoffResult."""
    try:
        latest = db.query(models.TakeoffResult).filter(
            models.TakeoffResult.drawing_id == drawing_id
        ).order_by(models.TakeoffResult.created_at.desc()).first()
        if latest:
            latest.symbol_counts = json.dumps(symbol_counts)
        else:
            db.add(models.TakeoffResult(
                drawing_id=drawing_id,
                symbol_counts=json.dumps(symbol_counts),
                ai_model_version="symbol-counts-v1",
            ))
        db.commit()
    except Exception as exc:
        logger.error(f"[detect_symbols] persist failed for {drawing_id}: {exc}")
        db.rollback()


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
