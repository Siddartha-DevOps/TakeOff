"""
TakeOff.ai — Drawing revision comparison.
Closes memory/TOGAL_PARITY_REAUDIT.md #8: "Drawing compare absent — fake
Rev A/B/C buttons; Comparison.jsx is a marketing page."

Revisions aren't a separate entity — two Drawings in the same project that
share a sheet_name (already a field users fill in on upload, see
routes/upload_routes.py) are revisions of the same sheet, ordered by
uploaded_at. That's enough to replace the hardcoded Rev A/B/C buttons in
Takeoff.jsx with real ones, without a schema change.
"""

import base64
import os
import sys
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import models
from auth import get_current_user
from database import get_db
from drawing_compare import auto_align, compare_available, compute_diff, manual_align, quantify_changes

router = APIRouter(prefix="/takeoff", tags=["Drawing Compare"])

COMPARE_UNAVAILABLE_DETAIL = (
    "Drawing compare isn't available yet — OpenCV isn't installed on the "
    "server (app/requirements.txt's opencv-python-headless + numpy, kept "
    "out of the base API image per CLAUDE.md's separate-service guardrail)."
)


def _get_drawing(drawing_id: int, current_user: models.User, db: Session) -> models.Drawing:
    drawing = db.query(models.Drawing).join(models.Project).filter(
        models.Drawing.id == drawing_id,
        models.Project.organization_id == current_user.organization_id,
    ).first()
    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")
    return drawing


@router.get("/drawings/{drawing_id}/revisions")
async def list_revisions(
    drawing_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Every drawing in the project sharing this one's sheet_name, oldest
    first, with a computed Rev A/B/C... label.
    """
    drawing = _get_drawing(drawing_id, current_user, db)
    if not drawing.sheet_name:
        return []

    siblings = db.query(models.Drawing).filter(
        models.Drawing.project_id == drawing.project_id,
        models.Drawing.sheet_name == drawing.sheet_name,
    ).order_by(models.Drawing.uploaded_at.asc()).all()

    return [
        {
            "id": d.id,
            "revision_label": f"Rev {chr(65 + i)}",
            "uploaded_at": d.uploaded_at,
            "is_current": d.id == siblings[-1].id,
            "original_filename": d.original_filename,
        }
        for i, d in enumerate(siblings)
    ]


class ComparePayload(BaseModel):
    compare_to_drawing_id: int
    # >=4 corresponding point pairs, plan-space pixels in each drawing's own
    # frame (same convention DrawingRenderer.jsx resolves clicks to for
    # scale calibration). Omit both for auto-align.
    manual_points_a: Optional[List[List[float]]] = None
    manual_points_b: Optional[List[List[float]]] = None


@router.post("/drawings/{drawing_id}/compare")
async def compare_drawings(
    drawing_id: int,
    payload: ComparePayload,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Overlay two sheets: blue/red diff over grey, auto-aligned by default
    (ORB features + RANSAC homography) or manually aligned from supplied
    point pairs. Returns the diff image (PNG, base64 data URI) plus
    one-click quantification (changed area, region counts, sqft if the
    sheet has a calibrated scale).
    """
    if not compare_available():
        raise HTTPException(status_code=503, detail=COMPARE_UNAVAILABLE_DETAIL)

    drawing_a = _get_drawing(drawing_id, current_user, db)
    drawing_b = _get_drawing(payload.compare_to_drawing_id, current_user, db)
    if drawing_a.project_id != drawing_b.project_id:
        raise HTTPException(status_code=400, detail="Drawings must be in the same project")

    import cv2
    import storage

    ai_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ai")
    sys.path.insert(0, ai_dir)
    from preprocessing import load_drawing

    # file_path may be an object-storage URI (memory/TOGAL_PARITY_REAUDIT.md
    # #12) — resolve_local_path() is a no-op for the still-supported
    # local-disk case, transparent download-to-temp otherwise.
    with storage.resolve_local_path(drawing_a.file_path) as path_a, \
         storage.resolve_local_path(drawing_b.file_path) as path_b:
        img_a = load_drawing(path_a, page_number=0)
        img_b = load_drawing(path_b, page_number=0)

    if payload.manual_points_a and payload.manual_points_b:
        try:
            aligned_b, _homography = manual_align(img_a, img_b, payload.manual_points_a, payload.manual_points_b)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        alignment_method = "manual"
        alignment_confidence = len(payload.manual_points_a)
    else:
        aligned_b, homography, inlier_count = auto_align(img_a, img_b)
        if homography is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Auto-alignment found only {inlier_count} matching features (need 10+). "
                    "Retry with manual_points_a/manual_points_b — at least 4 corresponding "
                    "points picked on each sheet."
                ),
            )
        alignment_method = "auto"
        alignment_confidence = inlier_count

    diff_image, removed_mask, added_mask = compute_diff(img_a, aligned_b)
    stats = quantify_changes(removed_mask, added_mask, scale_ratio=drawing_a.scale_ratio)

    success, encoded = cv2.imencode(".png", diff_image)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to encode diff image")
    diff_b64 = base64.b64encode(encoded.tobytes()).decode("ascii")

    return {
        "drawing_a_id": drawing_a.id,
        "drawing_b_id": drawing_b.id,
        "alignment_method": alignment_method,
        "alignment_confidence": alignment_confidence,
        "diff_image": f"data:image/png;base64,{diff_b64}",
        "quantification": stats,
    }
