from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import export_engine
import models
import repeating_groups
from auth import get_current_user
from database import get_db

router = APIRouter(prefix="/repeating", tags=["Repeating Groups"])

# Repeating Groups — memory/TOGAL_PARITY_REAUDIT.md #19. See
# repeating_groups.py's module docstring for how the multiplier actually
# reaches exports/handoff; this file is just CRUD + a preview endpoint.


def _get_project(project_id: int, current_user: models.User, db: Session) -> models.Project:
    project = db.query(models.Project).filter(
        models.Project.id == project_id,
        models.Project.organization_id == current_user.organization_id,
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _get_drawing_name(drawing: "models.Drawing") -> str:
    return drawing.sheet_number or drawing.sheet_name or drawing.original_filename


@router.get("/projects/{project_id}/master-units")
async def list_master_units(
    project_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = _get_project(project_id, current_user, db)
    units = db.query(models.MasterUnit).filter(models.MasterUnit.project_id == project.id).order_by(models.MasterUnit.created_at.asc()).all()
    return {
        "master_units": [repeating_groups.master_unit_to_dict(mu, _get_drawing_name(mu.drawing)) for mu in units],
    }


class MasterUnitCreate(BaseModel):
    drawing_id: int
    name: str
    instance_count: int = Field(ge=1, le=100000)
    notes: Optional[str] = None


@router.post("/projects/{project_id}/master-units")
async def create_master_unit(
    project_id: int,
    payload: MasterUnitCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = _get_project(project_id, current_user, db)
    drawing = db.query(models.Drawing).filter(
        models.Drawing.id == payload.drawing_id, models.Drawing.project_id == project.id,
    ).first()
    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found in this project")

    if repeating_groups.get_master_unit(db, drawing.id):
        raise HTTPException(status_code=400, detail="This drawing is already a master unit — update or delete the existing one instead")

    mu = models.MasterUnit(
        project_id=project.id, drawing_id=drawing.id, name=payload.name,
        instance_count=payload.instance_count, notes=payload.notes, created_by=current_user.id,
    )
    db.add(mu)
    db.commit()
    db.refresh(mu)
    return repeating_groups.master_unit_to_dict(mu, _get_drawing_name(drawing))


class MasterUnitUpdate(BaseModel):
    name: Optional[str] = None
    instance_count: Optional[int] = Field(default=None, ge=1, le=100000)
    notes: Optional[str] = None


@router.put("/master-units/{master_unit_id}")
async def update_master_unit(
    master_unit_id: int,
    payload: MasterUnitUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    mu = db.query(models.MasterUnit).filter(models.MasterUnit.id == master_unit_id).first()
    if not mu:
        raise HTTPException(status_code=404, detail="Master unit not found")
    _get_project(mu.project_id, current_user, db)

    if payload.name is not None:
        mu.name = payload.name
    if payload.instance_count is not None:
        mu.instance_count = payload.instance_count
    if payload.notes is not None:
        mu.notes = payload.notes
    db.commit()
    db.refresh(mu)
    return repeating_groups.master_unit_to_dict(mu, _get_drawing_name(mu.drawing))


@router.delete("/master-units/{master_unit_id}")
async def delete_master_unit(
    master_unit_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    mu = db.query(models.MasterUnit).filter(models.MasterUnit.id == master_unit_id).first()
    if not mu:
        raise HTTPException(status_code=404, detail="Master unit not found")
    _get_project(mu.project_id, current_user, db)
    db.delete(mu)
    db.commit()
    return {"deleted": True}


@router.get("/projects/{project_id}/preview")
async def preview_repeating_groups(
    project_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Before/after quantities for every drawing that's a master unit — lets
    the UI show "this drawing's own measured quantities" next to "what it
    contributes project-wide once the ×N is applied", so the multiplier is
    never a black box.
    """
    project = _get_project(project_id, current_user, db)
    units = db.query(models.MasterUnit).filter(models.MasterUnit.project_id == project.id).all()

    results = []
    for mu in units:
        base_rows = export_engine.extract_rows(db, mu.drawing)
        multiplied_rows = repeating_groups.apply_multiplier(db, mu.drawing, base_rows)
        results.append({
            "master_unit": repeating_groups.master_unit_to_dict(mu, _get_drawing_name(mu.drawing)),
            "base_rows": base_rows,
            "multiplied_rows": multiplied_rows,
        })
    return {"master_units": results}
