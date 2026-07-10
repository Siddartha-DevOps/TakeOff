"""
TakeOff.ai — Conditions
Closes the "auto-classify" gap in memory/TOGAL_GAP_ANALYSIS.md #9 /
TOGAL_PARITY_REAUDIT.md #5: detections had no way to be assigned to a named,
measured item (trade/space-type/unit). A Condition is that named item;
box-select -> assign (see Takeoff.jsx) tags annotations with a condition_id.

Conditions are project-scoped (not per-sheet) so the same condition
accumulates quantity across every sheet in a takeoff, matching how Togal
and CLAUDE.md §5 define them.
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models
import schemas
from auth import get_current_user
from database import get_db

router = APIRouter(tags=["Conditions"])


def _get_project(project_id: int, current_user: models.User, db: Session) -> models.Project:
    project = db.query(models.Project).filter(
        models.Project.id == project_id,
        models.Project.organization_id == current_user.organization_id,
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _get_condition(condition_id: int, current_user: models.User, db: Session) -> models.Condition:
    condition = db.query(models.Condition).join(models.Project).filter(
        models.Condition.id == condition_id,
        models.Project.organization_id == current_user.organization_id,
    ).first()
    if not condition:
        raise HTTPException(status_code=404, detail="Condition not found")
    return condition


@router.get("/projects/{project_id}/conditions", response_model=List[schemas.Condition])
async def list_conditions(
    project_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_project(project_id, current_user, db)
    return db.query(models.Condition).filter(
        models.Condition.project_id == project_id
    ).order_by(models.Condition.trade, models.Condition.name).all()


@router.post("/projects/{project_id}/conditions", response_model=schemas.Condition)
async def create_condition(
    project_id: int,
    payload: schemas.ConditionCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_project(project_id, current_user, db)
    condition = models.Condition(project_id=project_id, **payload.model_dump())
    db.add(condition)
    db.commit()
    db.refresh(condition)
    return condition


@router.put("/conditions/{condition_id}", response_model=schemas.Condition)
async def update_condition(
    condition_id: int,
    payload: schemas.ConditionUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    condition = _get_condition(condition_id, current_user, db)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(condition, field, value)
    db.commit()
    db.refresh(condition)
    return condition


@router.delete("/conditions/{condition_id}")
async def delete_condition(
    condition_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    condition = _get_condition(condition_id, current_user, db)
    db.delete(condition)
    db.commit()
    return {"status": "deleted", "condition_id": condition_id}
