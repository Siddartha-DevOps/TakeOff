"""
India BOQ endpoint: a drawing's detection result -> priced Indian BOQ.

Wires the estimating package (metric IS 1200 quantities -> DSR-priced BOQ ->
GST-finalized tender summary) onto a real, org-scoped drawing. This is the
India differentiator Togal.ai lacks: Togal stops at quantities; here the
deliverable is a BOQ priced against a Schedule of Rates with GST.

The rate book defaults to an illustrative CPWD-DSR-style **sample** — load a
real DSR/SOR edition (RateBook.from_rows) for production estimates.
See memory/INDIA_GTM_AND_GAP.md.
"""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

import models
from auth import get_current_user
from database import get_db
from estimating import RateBook, full_estimate
from estimating.export import boq_to_excel, boq_to_pdf

router = APIRouter(prefix="/india", tags=["India BOQ"])


def _get_drawing(drawing_id: int, current_user: models.User, db: Session) -> models.Drawing:
    drawing = db.query(models.Drawing).join(models.Project).filter(
        models.Drawing.id == drawing_id,
        models.Project.organization_id == current_user.organization_id,
    ).first()
    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")
    return drawing


def _latest_detection(drawing_id: int, db: Session) -> dict:
    result = (
        db.query(models.TakeoffResult)
        .filter(models.TakeoffResult.drawing_id == drawing_id)
        .order_by(models.TakeoffResult.created_at.desc())
        .first()
    )
    if not result or not result.detection_data:
        raise HTTPException(
            status_code=409,
            detail="No takeoff result for this drawing yet. Run AUTODETECT first.",
        )
    try:
        return json.loads(result.detection_data)
    except (json.JSONDecodeError, TypeError):
        raise HTTPException(status_code=500, detail="Stored detection data is not valid JSON")


def _estimate_for_drawing(
    drawing_id: int,
    overhead_profit_pct: float,
    contingency_pct: float,
    gst_rate: float,
    inter_state: bool,
    current_user: models.User,
    db: Session,
) -> dict:
    """Shared: build the full India estimate for a drawing (JSON + exports use it)."""
    _get_drawing(drawing_id, current_user, db)
    detection = _latest_detection(drawing_id, db)

    if min(overhead_profit_pct, contingency_pct, gst_rate) < 0:
        raise HTTPException(status_code=400, detail="percentages/rate must be non-negative")

    try:
        estimate = full_estimate(
            detection,
            RateBook.sample(),
            overhead_profit_pct=overhead_profit_pct,
            contingency_pct=contingency_pct,
            gst_rate=gst_rate,
            inter_state=inter_state,
        )
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=f"Could not build BOQ: {exc}")

    estimate["drawing_id"] = drawing_id
    estimate["rate_book_note"] = (
        "Illustrative sample rates — load the active CPWD DSR / state SOR edition "
        "for production estimates."
    )
    return estimate


@router.get("/drawings/{drawing_id}/boq")
async def drawing_boq(
    drawing_id: int,
    overhead_profit_pct: float = 15.0,
    contingency_pct: float = 3.0,
    gst_rate: float = 0.18,
    inter_state: bool = False,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the priced Indian BOQ + GST-finalized tender summary for a drawing.

    Query params tune the tender waterfall (overheads&profit %, contingency %,
    GST rate, intra/inter-state). Amounts in INR.
    """
    return _estimate_for_drawing(
        drawing_id, overhead_profit_pct, contingency_pct, gst_rate, inter_state,
        current_user, db,
    )


@router.get("/drawings/{drawing_id}/boq.{fmt}")
async def drawing_boq_export(
    drawing_id: int,
    fmt: str,
    overhead_profit_pct: float = 15.0,
    contingency_pct: float = 3.0,
    gst_rate: float = 0.18,
    inter_state: bool = False,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Download the BOQ as Excel (``xlsx``) or PDF (``pdf``)."""
    fmt = fmt.lower()
    if fmt not in ("xlsx", "pdf"):
        raise HTTPException(status_code=400, detail="format must be 'xlsx' or 'pdf'")

    estimate = _estimate_for_drawing(
        drawing_id, overhead_profit_pct, contingency_pct, gst_rate, inter_state,
        current_user, db,
    )

    if fmt == "xlsx":
        content = boq_to_excel(estimate)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        content = boq_to_pdf(estimate)
        media = "application/pdf"

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"boq_drawing_{drawing_id}_{ts}.{fmt}"
    return StreamingResponse(
        iter([content]),
        media_type=media,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
