"""
TakeOff.ai — Active-learning review queue (Phase 6).

Closes the training flywheel online: surface the drawings/detections the model is
least sure about (or that users keep correcting) so they get labeled next, feeding
``ml/training/export_corrections`` → retrain.

Endpoints (org-isolated, like the rest of routes/):
- GET /active-learning/projects/{project_id}/review-queue
    drawings ranked by priority (uncertainty + human disagreement)
- GET /active-learning/projects/{project_id}/uncertain-detections
    the most-uncertain individual AI detections, spread across drawings

Ranking logic lives in ml/active_learning (pure, unit-tested); this layer only
supplies DB rows and shapes the response.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

import models
from auth import get_current_user
from database import get_db
from ml.active_learning.queue import aggregate_drawing_stats, detection_items
from ml.active_learning.sampler import rank_drawings_for_review, select_batch

router = APIRouter(prefix="/active-learning", tags=["Active Learning"])


def _get_project(project_id: int, current_user: models.User, db: Session) -> models.Project:
    project = (
        db.query(models.Project)
        .filter(
            models.Project.id == project_id,
            models.Project.organization_id == current_user.organization_id,
        )
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.get("/projects/{project_id}/review-queue")
async def review_queue(
    project_id: int,
    limit: int = Query(20, ge=1, le=200),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Drawings ranked by labeling priority (model uncertainty + user disagreement)."""
    _get_project(project_id, current_user, db)

    det_rows = (
        db.query(models.Detection.drawing_id, models.Detection.confidence)
        .filter(models.Detection.project_id == project_id, models.Detection.source == "ai")
        .all()
    )
    corr_rows = (
        db.query(models.CorrectionEvent.drawing_id, models.CorrectionEvent.action)
        .filter(models.CorrectionEvent.project_id == project_id)
        .all()
    )

    stats = aggregate_drawing_stats(
        [(d, c) for d, c in det_rows],
        [(d, a) for d, a in corr_rows],
    )
    ranked = rank_drawings_for_review(stats)[:limit]

    # Attach human-readable drawing names for the ones we're returning.
    ids = [r["drawing_id"] for r in ranked]
    names = {}
    if ids:
        for d in db.query(models.Drawing).filter(models.Drawing.id.in_(ids)).all():
            names[d.id] = d.sheet_name or d.original_filename
    for r in ranked:
        r["sheet_name"] = names.get(r["drawing_id"])

    return {"project_id": project_id, "count": len(ranked), "queue": ranked}


@router.get("/projects/{project_id}/uncertain-detections")
async def uncertain_detections(
    project_id: int,
    limit: int = Query(50, ge=1, le=500),
    diversify: bool = Query(True, description="spread the batch across drawings"),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The most-uncertain individual AI detections, optionally spread across drawings."""
    _get_project(project_id, current_user, db)

    rows = (
        db.query(
            models.Detection.id,
            models.Detection.drawing_id,
            models.Detection.class_label,
            models.Detection.confidence,
        )
        .filter(models.Detection.project_id == project_id, models.Detection.source == "ai")
        .all()
    )
    items = detection_items([(r[0], r[1], r[2], r[3]) for r in rows])
    picked = select_batch(
        items, limit, strategy="least_confidence",
        diversity_key="drawing_id" if diversify else None,
    )
    return {"project_id": project_id, "count": len(picked), "detections": picked}
