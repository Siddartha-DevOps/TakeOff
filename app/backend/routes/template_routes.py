"""
TakeOff.ai — Classification libraries (reusable condition templates).
Closes the Togal-parity gap "Classification libraries — reusable templates,
import/export" — previously only a pricing-page bullet ("Personal library" /
"Classification library template" in mockData.js's PRICING_PLANS) with no
actual feature behind it.

Org-scoped (not per-project, not per-user): a template is a named,
reusable set of Condition definitions any project in the org can draw
from. Two ways in, two ways out:
  - in-app library: save a project's current conditions as a template,
    apply a template into any project.
  - file-based: export a template (or a project's live conditions) as a
    downloadable JSON payload, import a JSON payload directly without
    needing a saved template row first.
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models
import schemas
from auth import get_current_user
from database import get_db

router = APIRouter(tags=["Classification Templates"])


def _get_project(project_id: int, current_user: models.User, db: Session) -> models.Project:
    project = db.query(models.Project).filter(
        models.Project.id == project_id,
        models.Project.organization_id == current_user.organization_id,
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _get_template(template_id: int, current_user: models.User, db: Session) -> models.ConditionTemplate:
    template = db.query(models.ConditionTemplate).filter(
        models.ConditionTemplate.id == template_id,
        models.ConditionTemplate.organization_id == current_user.organization_id,
    ).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


def _item_fields(item) -> dict:
    return {
        "name": item.name, "trade": item.trade, "space_type": item.space_type,
        "annotation_type": item.annotation_type, "unit": item.unit, "color": item.color,
        "waste_percent": item.waste_percent, "unit_cost": item.unit_cost,
    }


@router.get("/condition-templates", response_model=List[schemas.ConditionTemplate])
async def list_templates(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return db.query(models.ConditionTemplate).filter(
        models.ConditionTemplate.organization_id == current_user.organization_id
    ).order_by(models.ConditionTemplate.name).all()


@router.get("/condition-templates/{template_id}", response_model=schemas.ConditionTemplate)
async def get_template(
    template_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _get_template(template_id, current_user, db)


@router.post("/projects/{project_id}/conditions/save-as-template", response_model=schemas.ConditionTemplate)
async def save_project_as_template(
    project_id: int,
    payload: schemas.ConditionTemplateCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = _get_project(project_id, current_user, db)
    conditions = db.query(models.Condition).filter(models.Condition.project_id == project.id).all()
    if not conditions:
        raise HTTPException(status_code=400, detail="Project has no conditions to save as a template")

    template = models.ConditionTemplate(
        organization_id=current_user.organization_id,
        name=payload.name,
        description=payload.description,
        created_by=current_user.id,
    )
    db.add(template)
    db.flush()  # assigns template.id without committing yet
    for c in conditions:
        db.add(models.ConditionTemplateItem(template_id=template.id, **_item_fields(c)))
    db.commit()
    db.refresh(template)
    return template


@router.post("/projects/{project_id}/conditions/apply-template/{template_id}", response_model=List[schemas.Condition])
async def apply_template_to_project(
    project_id: int,
    template_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = _get_project(project_id, current_user, db)
    template = _get_template(template_id, current_user, db)

    created = []
    for item in template.items:
        condition = models.Condition(project_id=project.id, **_item_fields(item))
        db.add(condition)
        created.append(condition)
    db.commit()
    for c in created:
        db.refresh(c)
    return created


@router.post("/projects/{project_id}/conditions/import", response_model=List[schemas.Condition])
async def import_conditions_json(
    project_id: int,
    payload: schemas.ConditionTemplateExport,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Direct file-based import — a previously exported .json payload, no saved template row required."""
    project = _get_project(project_id, current_user, db)
    created = []
    for item in payload.items:
        condition = models.Condition(project_id=project.id, **item.model_dump())
        db.add(condition)
        created.append(condition)
    db.commit()
    for c in created:
        db.refresh(c)
    return created


@router.get("/projects/{project_id}/conditions/export", response_model=schemas.ConditionTemplateExport)
async def export_project_conditions(
    project_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """File-based export of a project's live conditions — the frontend downloads this as .json."""
    project = _get_project(project_id, current_user, db)
    conditions = db.query(models.Condition).filter(models.Condition.project_id == project.id).all()
    return schemas.ConditionTemplateExport(
        name=f"{project.name} — Conditions",
        description=None,
        items=[schemas.ConditionBase(**_item_fields(c)) for c in conditions],
    )


@router.put("/condition-templates/{template_id}", response_model=schemas.ConditionTemplate)
async def update_template(
    template_id: int,
    payload: schemas.ConditionTemplateUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    template = _get_template(template_id, current_user, db)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(template, field, value)
    db.commit()
    db.refresh(template)
    return template


@router.delete("/condition-templates/{template_id}")
async def delete_template(
    template_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    template = _get_template(template_id, current_user, db)
    db.delete(template)
    db.commit()
    return {"status": "deleted", "template_id": template_id}
