"""
TakeOff.ai — Plan-set organizer.

Turns a project's flat drawing list into a discipline-grouped, ordered sheet tree
(Togal's "auto-name & organize hundreds of sheets"), and lets estimators fix the
OCR-derived sheet number / name / discipline.

- GET   /api/plan-set/projects/{project_id}         → grouped, ordered sheets
- PATCH /api/plan-set/drawings/{drawing_id}         → rename / re-classify a sheet

Grouping/ordering is pure (plan_organizer.py); this layer is org-isolated DB I/O.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

import models
from auth import get_current_user
from database import get_db
from plan_organizer import discipline_from_sheet_number, group_by_discipline

router = APIRouter(prefix="/plan-set", tags=["Plan Set"])


def _require_project(project_id: int, current_user: models.User, db: Session) -> models.Project:
    project = (
        db.query(models.Project)
        .filter(models.Project.id == project_id,
                models.Project.organization_id == current_user.organization_id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _sheet_dict(d: models.Drawing) -> dict:
    return {
        "id": d.id,
        "sheet_number": d.sheet_number,
        "sheet_name": d.sheet_name or d.original_filename,
        "discipline": d.discipline,
        "page_number": d.page_number,
        "total_pages": d.total_pages,
        "upload_batch_id": d.upload_batch_id,
    }


@router.get("/projects/{project_id}")
async def get_plan_set(
    project_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The project's sheets, grouped by discipline and ordered by sheet number."""
    _require_project(project_id, current_user, db)
    drawings = (
        db.query(models.Drawing)
        .filter(models.Drawing.project_id == project_id)
        .all()
    )
    groups = group_by_discipline([_sheet_dict(d) for d in drawings])
    return {"project_id": project_id, "sheet_count": len(drawings), "disciplines": groups}


class SheetPatch(BaseModel):
    sheet_name: Optional[str] = None
    sheet_number: Optional[str] = None
    discipline: Optional[str] = None


@router.patch("/drawings/{drawing_id}")
async def update_sheet(
    drawing_id: int,
    body: SheetPatch,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Fix a sheet's number / name / discipline.

    If ``sheet_number`` is set but ``discipline`` is not, the discipline is
    re-derived from the new number (matching how OCR classifies on ingest).
    """
    drawing = (
        db.query(models.Drawing)
        .join(models.Project)
        .filter(models.Drawing.id == drawing_id,
                models.Project.organization_id == current_user.organization_id)
        .first()
    )
    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")

    if body.sheet_name is not None:
        drawing.sheet_name = body.sheet_name
    if body.sheet_number is not None:
        drawing.sheet_number = body.sheet_number
        if body.discipline is None:
            drawing.discipline = discipline_from_sheet_number(body.sheet_number)
    if body.discipline is not None:
        drawing.discipline = body.discipline

    db.commit()
    db.refresh(drawing)
    return _sheet_dict(drawing)
