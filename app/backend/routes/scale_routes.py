"""Per-drawing scale detection, confirmation, and two-point calibration."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
import numpy as np

import models
import storage
from ai.scale_detection import (
    extract_pdf_scale_candidates,
    run_ocr_for_scale,
    scale_ratio_to_string,
    select_scale_candidate,
)
from auth import get_current_user
from canonical_takeoff import CanonicalAnnotationError, synchronize_corrected_takeoff
from database import get_db

router = APIRouter(prefix="/uploads/drawings", tags=["Scale Calibration"])

REFERENCE_DPI = 300.0
PDF_POINTS_PER_INCH = 72.0


class ScaleCandidate(BaseModel):
    ratio: Optional[float] = None
    text: str = ""
    confidence: float = 0.0
    method: str
    pattern_type: Optional[str] = None


class ScaleSuggestion(BaseModel):
    ratio: Optional[float]
    label: Optional[str]
    raw_text: str
    confidence: float
    method: str
    conflict: bool = False
    requires_confirmation: bool = True
    source_dpi: Optional[float] = None
    candidates: list[ScaleCandidate] = Field(default_factory=list)


class ScaleResponse(BaseModel):
    scale_ratio: Optional[float]
    scale_label: Optional[str]
    scale_source: Optional[str]
    scale_calibrated_at: Optional[datetime]
    detection_method: Optional[str]
    confidence: Optional[float]
    auto_detected: bool
    manually_calibrated: bool
    manual_confirmation_required: bool
    plan_dpi: Optional[float]
    suggestion: Optional[ScaleSuggestion]


class CalibratePayload(BaseModel):
    point1: list[float] = Field(..., min_length=2, max_length=2)
    point2: list[float] = Field(..., min_length=2, max_length=2)
    render_scale: float = Field(gt=0)
    real_world_distance: float = Field(gt=0)
    unit: Literal["ft", "in"]


def _get_drawing(drawing_id: int, current_user: models.User, db: Session) -> models.Drawing:
    drawing = db.query(models.Drawing).join(models.Project).filter(
        models.Drawing.id == drawing_id,
        models.Project.organization_id == current_user.organization_id,
    ).first()
    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")
    return drawing


def _dedupe_candidates(candidates: list[dict]) -> list[dict]:
    distinct: list[dict] = []
    for candidate in candidates:
        ratio = candidate.get("ratio")
        if ratio is None:
            continue
        existing = next((item for item in distinct if abs(item["ratio"] - ratio) / max(item["ratio"], ratio) <= 0.02), None)
        if existing is None:
            distinct.append(candidate)
        elif candidate.get("method", "").startswith("title_block") and not existing.get("method", "").startswith("title_block"):
            distinct[distinct.index(existing)] = candidate
    return distinct


def _raster_dpi(local_path: str) -> Optional[float]:
    """Return a trustworthy square-pixel DPI, never a guessed fallback."""
    try:
        from PIL import Image
        with Image.open(local_path) as image:
            dpi = image.info.get("dpi") or image.info.get("resolution")
            if not isinstance(dpi, (tuple, list)) or len(dpi) < 2:
                return None
            x_dpi, y_dpi = float(dpi[0]), float(dpi[1])
            if x_dpi <= 0 or y_dpi <= 0 or abs(x_dpi - y_dpi) / max(x_dpi, y_dpi) > 0.02:
                return None
            return (x_dpi + y_dpi) / 2.0
    except Exception:
        return None


def _load_scale_image(local_path: str, file_type: str, page_number: int) -> np.ndarray:
    """Materialized-source image loader that does not require OpenCV."""
    if file_type == "PDF":
        import fitz
        with fitz.open(local_path) as document:
            if page_number < 0 or page_number >= document.page_count:
                raise ValueError(f"PDF page {page_number} is out of range")
            pixmap = document.load_page(page_number).get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            return np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, pixmap.n)
    from PIL import Image
    with Image.open(local_path) as image:
        if getattr(image, "n_frames", 1) > 1:
            image.seek(page_number)
        return np.asarray(image.convert("RGB"))


def _run_ocr_suggestion(drawing: models.Drawing) -> Optional[dict]:
    """Materialize one source object and inspect only this Drawing's page."""
    try:
        page_number = int(drawing.page_number or 0)
        file_type = str(drawing.file_type or "").upper()
        with storage.resolve_local_path(drawing.file_path) as local_path:
            source_dpi = PDF_POINTS_PER_INCH if file_type == "PDF" else None
            candidates: list[dict] = []
            if file_type == "PDF":
                candidates.extend(extract_pdf_scale_candidates(local_path, page_number))
            else:
                source_dpi = _raster_dpi(local_path)

            image = _load_scale_image(local_path, file_type, page_number)
            raster_result = run_ocr_for_scale(image)
            if raster_result and raster_result.get("ratio") is not None:
                candidates.extend(raster_result.get("candidates") or [raster_result])

        selected = select_scale_candidate(_dedupe_candidates(candidates))
        if selected is None:
            # Preserve an unresolved graphic-bar signal so the UI can explain
            # why manual calibration is required, without assigning a ratio.
            if raster_result and raster_result.get("method") == "scale_bar_unresolved":
                selected = raster_result
            else:
                return None
        ratio = selected.get("ratio")
        return {
            "ratio": ratio,
            "label": scale_ratio_to_string(ratio) if ratio else None,
            "raw_text": selected.get("raw_text") or selected.get("text", ""),
            "confidence": float(selected.get("confidence", 0.0) or 0.0),
            "method": selected.get("method", "ocr_text"),
            "conflict": bool(selected.get("conflict")),
            "requires_confirmation": True,
            "source_dpi": source_dpi,
            "candidates": selected.get("candidates", []),
        }
    except Exception:
        return None


def _cached_suggestion(drawing: models.Drawing) -> Optional[dict]:
    if not drawing.ocr_scale_method:
        return None
    try:
        candidates = json.loads(drawing.ocr_scale_candidates or "[]")
    except (TypeError, json.JSONDecodeError):
        candidates = []
    return {
        "ratio": drawing.ocr_scale_ratio,
        "label": scale_ratio_to_string(drawing.ocr_scale_ratio) if drawing.ocr_scale_ratio else None,
        "raw_text": drawing.ocr_scale_text or "",
        "confidence": float(drawing.ocr_scale_confidence or 0.0),
        "method": drawing.ocr_scale_method,
        "conflict": bool(drawing.ocr_scale_conflict),
        "requires_confirmation": True,
        "source_dpi": None if str(drawing.file_type or "").upper() != "PDF" else PDF_POINTS_PER_INCH,
        "candidates": candidates,
    }


def _active_plan_dpi(drawing: models.Drawing) -> Optional[float]:
    if drawing.scale_dpi and drawing.scale_dpi > 0:
        return float(drawing.scale_dpi)
    if str(drawing.file_type or "").upper() == "PDF" and drawing.scale_ratio:
        return PDF_POINTS_PER_INCH
    # Backward compatibility for historical manual raster calibration, whose
    # ratio was explicitly derived in the virtual 300-DPI coordinate system.
    if drawing.scale_source == "manual" and drawing.scale_ratio:
        return REFERENCE_DPI
    return None


def _source_plan_dpi(drawing: models.Drawing) -> Optional[float]:
    if str(drawing.file_type or "").upper() == "PDF":
        return PDF_POINTS_PER_INCH
    try:
        with storage.resolve_local_path(drawing.file_path) as local_path:
            return _raster_dpi(local_path)
    except Exception:
        return None


def _to_response(drawing: models.Drawing, suggestion: Optional[dict]) -> ScaleResponse:
    manual = drawing.scale_source == "manual"
    auto = drawing.scale_source == "ocr"
    requires_confirmation = bool(
        getattr(drawing, "scale_requires_confirmation", True)
        or not drawing.scale_ratio
        or drawing.scale_source not in {"manual", "ocr"}
    )
    return ScaleResponse(
        scale_ratio=drawing.scale_ratio,
        scale_label=drawing.scale,
        scale_source=drawing.scale_source,
        scale_calibrated_at=drawing.scale_calibrated_at,
        detection_method=drawing.scale_detection_method,
        confidence=drawing.scale_confidence,
        auto_detected=auto,
        manually_calibrated=manual,
        manual_confirmation_required=requires_confirmation,
        plan_dpi=_active_plan_dpi(drawing),
        suggestion=ScaleSuggestion(**suggestion) if suggestion else None,
    )


def _remeasure_after_scale_change(db: Session, drawing: models.Drawing, user_id: int) -> None:
    """Atomically rebuild measurements/quantities from canonical annotations."""
    if drawing.annotations_data is None:
        # Legacy AI results without a canonical annotation document cannot be
        # safely remeasured. Invalidate their derived measurements so no
        # export/estimate can leak the old scale; geometry remains available
        # for review and the next takeoff run will rebuild quantities.
        for detection in db.query(models.Detection).filter(
            models.Detection.drawing_id == drawing.id
        ).all():
            for measurement in list(detection.measurements):
                db.delete(measurement)
        for result in db.query(models.TakeoffResult).filter(
            models.TakeoffResult.drawing_id == drawing.id
        ).all():
            result.quantities_data = "[]"
        return
    annotations = json.loads(drawing.annotations_data)
    projection = synchronize_corrected_takeoff(db, drawing, annotations)
    encoded = json.dumps(projection["annotations"], separators=(",", ":"))
    if drawing.annotations_data != encoded:
        drawing.annotations_data = encoded
        db.add(models.AnnotationRevision(
            drawing_id=drawing.id,
            created_by_id=user_id,
            annotations_data=encoded,
            annotation_count=len(projection["annotations"]),
        ))


@router.get("/{drawing_id}/scale", response_model=ScaleResponse)
async def get_scale(
    drawing_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    drawing = _get_drawing(drawing_id, current_user, db)
    suggestion = None
    if drawing.scale_source != "manual":
        if drawing.ocr_scale_method is None:
            detected = _run_ocr_suggestion(drawing)
            drawing.ocr_scale_method = detected["method"] if detected else "not_detected"
            drawing.ocr_scale_ratio = detected.get("ratio") if detected else None
            drawing.ocr_scale_text = detected.get("raw_text", "")[:255] if detected else None
            drawing.ocr_scale_confidence = detected.get("confidence", 0.0) if detected else None
            drawing.ocr_scale_conflict = bool(detected and detected.get("conflict"))
            drawing.ocr_scale_candidates = json.dumps(detected.get("candidates", [])) if detected else "[]"
            db.commit()
            db.refresh(drawing)
        suggestion = _cached_suggestion(drawing)
        if suggestion and suggestion["method"] == "not_detected":
            suggestion = None
        if drawing.scale_source == "ocr" and not drawing.scale_requires_confirmation:
            suggestion = None
    return _to_response(drawing, suggestion)


def _set_active_scale(
    drawing: models.Drawing, *, ratio: float, source: str, method: str,
    confidence: float, plan_dpi: float,
) -> None:
    drawing.scale_ratio = ratio
    drawing.scale = scale_ratio_to_string(ratio)
    drawing.scale_source = source
    drawing.scale_detection_method = method
    drawing.scale_confidence = confidence
    drawing.scale_requires_confirmation = False
    drawing.scale_dpi = plan_dpi
    drawing.scale_calibrated_at = datetime.now(timezone.utc)


@router.post("/{drawing_id}/scale/calibrate", response_model=ScaleResponse)
async def calibrate_scale(
    drawing_id: int,
    payload: CalibratePayload,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    drawing = _get_drawing(drawing_id, current_user, db)
    distance = math.hypot(
        payload.point2[0] - payload.point1[0], payload.point2[1] - payload.point1[1]
    ) / payload.render_scale
    if distance <= 0:
        raise HTTPException(status_code=400, detail="The two calibration points must not be identical")
    real_inches = payload.real_world_distance * (12.0 if payload.unit == "ft" else 1.0)
    plan_units_per_inch = PDF_POINTS_PER_INCH if str(drawing.file_type or "").upper() == "PDF" else REFERENCE_DPI
    ratio = real_inches * plan_units_per_inch / distance
    if not math.isfinite(ratio) or ratio < 2 or ratio > 10000:
        raise HTTPException(status_code=422, detail="Calibration produced an implausible drawing scale")
    try:
        _set_active_scale(
            drawing, ratio=ratio, source="manual", method="manual_two_point",
            confidence=1.0, plan_dpi=plan_units_per_inch,
        )
        _remeasure_after_scale_change(db, drawing, current_user.id)
        db.commit()
        db.refresh(drawing)
    except (CanonicalAnnotationError, json.JSONDecodeError) as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=f"Could not remeasure annotations: {exc}") from exc
    return _to_response(drawing, suggestion=None)


@router.post("/{drawing_id}/scale/accept-suggestion", response_model=ScaleResponse)
async def accept_scale_suggestion(
    drawing_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    drawing = _get_drawing(drawing_id, current_user, db)
    if drawing.ocr_scale_ratio is None:
        raise HTTPException(status_code=400, detail="No numeric scale suggestion is available")
    if drawing.ocr_scale_conflict:
        raise HTTPException(status_code=409, detail="Conflicting scale candidates require manual calibration")
    plan_dpi = _source_plan_dpi(drawing)
    if not plan_dpi:
        raise HTTPException(
            status_code=409,
            detail="This raster has no reliable DPI metadata; use two-point manual calibration",
        )
    try:
        _set_active_scale(
            drawing, ratio=float(drawing.ocr_scale_ratio), source="ocr",
            method=drawing.ocr_scale_method or "ocr_text",
            confidence=float(drawing.ocr_scale_confidence or 0.0), plan_dpi=float(plan_dpi),
        )
        _remeasure_after_scale_change(db, drawing, current_user.id)
        db.commit()
        db.refresh(drawing)
    except (CanonicalAnnotationError, json.JSONDecodeError) as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=f"Could not remeasure annotations: {exc}") from exc
    return _to_response(drawing, suggestion=None)
