"""
TakeOff.ai — Scale Calibration
Closes the gap flagged in memory/TOGAL_PARITY_REAUDIT.md #2: scale was
hardcoded/OCR-only with no user-correctable calibration step. Every
measurement (area, linear feet) depends on this being right.

Two ways to set a Sheet's (Drawing's) scale:
  - Manual two-point calibration: user clicks two points on the plan and
    enters the real-world distance between them (ground truth, always wins).
  - OCR suggestion: ai/scale_detection.py already parses scale notations
    ("1/8"=1'-0"", "1:96", ...) off the sheet; this wires that up as an
    accept/reject suggestion instead of a silently-assumed default.
"""

import os
import sys
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import models
from auth import get_current_user
from database import get_db

router = APIRouter(prefix="/uploads/drawings", tags=["Scale Calibration"])

# ai/preprocessing.py rasterizes every PDF page at this DPI, and scale_ratio is
# defined against that same pixel space so it plugs straight into
# ai/preprocessing.pixels_to_feet() / pixels_to_sqft() unchanged.
REFERENCE_DPI = 300
# react-pdf / PDF.js report coordinates in PDF points at scale=1 (72 pt/inch),
# the same convention PyMuPDF's `zoom = dpi / 72.0` rasterization is defined against.
PDF_POINTS_PER_INCH = 72


class ScaleSuggestion(BaseModel):
    ratio: float
    label: str
    raw_text: str
    confidence: float
    method: str


class ScaleResponse(BaseModel):
    scale_ratio: Optional[float]
    scale_label: Optional[str]
    scale_source: Optional[str]
    scale_calibrated_at: Optional[datetime]
    suggestion: Optional[ScaleSuggestion]


class CalibratePayload(BaseModel):
    # Points are in plan-space pixels (native image pixels, or PDF points at
    # scale=1 — see DrawingRenderer.jsx's toPlanSpacePoint()). render_scale is
    # an extra safety factor in case a caller ever sends un-normalized,
    # still-zoomed screen coordinates; the frontend always sends 1.
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


def _run_ocr_suggestion(drawing: models.Drawing) -> Optional[dict]:
    """Best-effort OCR scale read. Never raises — missing deps/model degrade to None."""
    try:
        ai_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ai")
        sys.path.insert(0, ai_dir)
        from preprocessing import load_drawing
        from scale_detection import run_ocr_for_scale, scale_ratio_to_string
    except ImportError:
        return None

    try:
        img = load_drawing(drawing.file_path, page_number=0)
        result = run_ocr_for_scale(img)
    except Exception:
        return None

    if not result or result.get("method") == "default":
        return None  # nothing legible found — don't suggest the fallback as a "suggestion"

    return {
        "ratio": result["ratio"],
        "label": scale_ratio_to_string(result["ratio"]),
        "raw_text": result.get("text", ""),
        "confidence": result.get("confidence", 0.0),
        "method": result.get("method", "ocr_text"),
    }


def _to_response(drawing: models.Drawing, suggestion: Optional[dict]) -> ScaleResponse:
    return ScaleResponse(
        scale_ratio=drawing.scale_ratio,
        scale_label=drawing.scale,
        scale_source=drawing.scale_source,
        scale_calibrated_at=drawing.scale_calibrated_at,
        suggestion=ScaleSuggestion(**suggestion) if suggestion else None,
    )


@router.get("/{drawing_id}/scale", response_model=ScaleResponse)
async def get_scale(
    drawing_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Current calibration (if any) plus an OCR suggestion when it hasn't been
    manually confirmed yet. OCR only runs once per drawing — cached on the row."""
    drawing = _get_drawing(drawing_id, current_user, db)

    suggestion = None
    if drawing.scale_source != "manual":
        if drawing.ocr_scale_ratio is None:
            ocr = _run_ocr_suggestion(drawing)
            if ocr:
                drawing.ocr_scale_ratio = ocr["ratio"]
                drawing.ocr_scale_text = ocr["raw_text"]
                drawing.ocr_scale_confidence = ocr["confidence"]
                db.commit()
                db.refresh(drawing)

        if drawing.ocr_scale_ratio is not None and drawing.ocr_scale_ratio != drawing.scale_ratio:
            from scale_detection import scale_ratio_to_string
            suggestion = {
                "ratio": drawing.ocr_scale_ratio,
                "label": scale_ratio_to_string(drawing.ocr_scale_ratio),
                "raw_text": drawing.ocr_scale_text or "",
                "confidence": drawing.ocr_scale_confidence or 0.0,
                "method": "ocr_text",
            }

    return _to_response(drawing, suggestion)


@router.post("/{drawing_id}/scale/calibrate", response_model=ScaleResponse)
async def calibrate_scale(
    drawing_id: int,
    payload: CalibratePayload,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Manual two-point calibration. Always wins over any OCR suggestion —
    this is ground truth the user measured against the actual sheet."""
    drawing = _get_drawing(drawing_id, current_user, db)

    from scale_detection import scale_ratio_to_string

    dx = payload.point2[0] - payload.point1[0]
    dy = payload.point2[1] - payload.point1[1]
    screen_pixel_distance = (dx ** 2 + dy ** 2) ** 0.5
    if screen_pixel_distance <= 0:
        raise HTTPException(status_code=400, detail="The two calibration points must not be identical")

    # Undo the on-screen zoom to get back to native plan-space pixels.
    plan_pixel_distance = screen_pixel_distance / payload.render_scale

    if drawing.file_type == "PDF":
        # Native PDF points (scale=1) -> the 300-DPI raster pixel space
        # ai/preprocessing.py's PyMuPDF rasterization produces.
        reference_pixel_distance = plan_pixel_distance * (REFERENCE_DPI / PDF_POINTS_PER_INCH)
    else:
        # Raster uploads load 1:1 via cv2.imread (no resampling) — already the
        # same pixel space ai/detection_engine.py operates on.
        reference_pixel_distance = plan_pixel_distance

    real_world_feet = payload.real_world_distance if payload.unit == "ft" else payload.real_world_distance / 12.0

    feet_per_pixel = real_world_feet / reference_pixel_distance
    scale_ratio = feet_per_pixel * 12.0 * REFERENCE_DPI

    drawing.scale_ratio = scale_ratio
    drawing.scale = scale_ratio_to_string(scale_ratio)
    drawing.scale_source = "manual"
    drawing.scale_calibrated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(drawing)

    return _to_response(drawing, suggestion=None)


@router.post("/{drawing_id}/scale/accept-suggestion", response_model=ScaleResponse)
async def accept_scale_suggestion(
    drawing_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Promote the cached OCR suggestion to the active scale."""
    drawing = _get_drawing(drawing_id, current_user, db)

    if drawing.ocr_scale_ratio is None:
        raise HTTPException(status_code=400, detail="No OCR scale suggestion available for this drawing")

    from scale_detection import scale_ratio_to_string

    drawing.scale_ratio = drawing.ocr_scale_ratio
    drawing.scale = scale_ratio_to_string(drawing.ocr_scale_ratio)
    drawing.scale_source = "ocr"
    drawing.scale_calibrated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(drawing)

    return _to_response(drawing, suggestion=None)
