"""
TakeOff.ai — Correction Events
The training-data flywheel (CLAUDE.md §2/§5): log every accept/reject/edit/
relabel a user makes on an AI (or manual) annotation. Closes the gap in
memory/TOGAL_PARITY_REAUDIT.md #4 — the CorrectionEvent table didn't exist
and the Accept/Edit buttons in Takeoff.jsx's DetectionHoverCard were dead.

annotation_id matches the frontend Annotation.id (see
frontend/src/annotations/types.js) rather than a hard foreign key, because
annotations themselves aren't persisted as rows yet — still JSON blobs in
TakeoffResult. drawing_id is optional for the same reason a user can browse
the demo canvas before any sheet is uploaded.
"""

import json
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models
import schemas
from auth import get_current_user
from database import get_db

router = APIRouter(tags=["Correction Events"])


def _get_project(project_id: int, current_user: models.User, db: Session) -> models.Project:
    project = db.query(models.Project).filter(
        models.Project.id == project_id,
        models.Project.organization_id == current_user.organization_id,
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _to_response(event: models.CorrectionEvent) -> schemas.CorrectionEvent:
    return schemas.CorrectionEvent(
        id=event.id,
        project_id=event.project_id,
        drawing_id=event.drawing_id,
        annotation_id=event.annotation_id,
        annotation_type=event.annotation_type,
        action=event.action,
        before=json.loads(event.before) if event.before else None,
        after=json.loads(event.after) if event.after else None,
        user_id=event.user_id,
        created_at=event.created_at,
    )


@router.post("/projects/{project_id}/corrections", response_model=schemas.CorrectionEvent)
async def create_correction(
    project_id: int,
    payload: schemas.CorrectionEventCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_project(project_id, current_user, db)

    if payload.drawing_id is not None:
        drawing = db.query(models.Drawing).filter(
            models.Drawing.id == payload.drawing_id,
            models.Drawing.project_id == project_id,
        ).first()
        if not drawing:
            raise HTTPException(status_code=404, detail="Drawing not found in this project")

    event = models.CorrectionEvent(
        project_id=project_id,
        drawing_id=payload.drawing_id,
        annotation_id=payload.annotation_id,
        annotation_type=payload.annotation_type,
        action=payload.action,
        before=json.dumps(payload.before) if payload.before is not None else None,
        after=json.dumps(payload.after) if payload.after is not None else None,
        user_id=current_user.id,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return _to_response(event)


@router.get("/projects/{project_id}/corrections", response_model=List[schemas.CorrectionEvent])
async def list_corrections(
    project_id: int,
    drawing_id: Optional[int] = None,
    limit: int = 100,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_project(project_id, current_user, db)

    query = db.query(models.CorrectionEvent).filter(
        models.CorrectionEvent.project_id == project_id
    )
    if drawing_id is not None:
        query = query.filter(models.CorrectionEvent.drawing_id == drawing_id)

    events = query.order_by(models.CorrectionEvent.created_at.desc()).limit(min(limit, 500)).all()
    return [_to_response(e) for e in events]
