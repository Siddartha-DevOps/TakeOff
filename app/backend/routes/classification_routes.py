"""
TakeOff.ai — classification-library templates.

Org-level reusable classification sets (Togal's "classification library
template"): create/edit templates, seed the built-in default, and apply a
template to a project (creating Condition rows). Classification logic is pure
(classification.py); this layer is org-isolated DB I/O.
"""

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

import models
from auth import get_current_user
from classification import default_template, items_to_conditions, validate_items
from database import get_db

router = APIRouter(prefix="/classifications", tags=["Classifications"])


def _to_dict(t: models.ClassificationTemplate) -> dict:
    try:
        items = json.loads(t.data) if t.data else []
    except (json.JSONDecodeError, TypeError):
        items = []
    return {
        "id": t.id, "name": t.name, "description": t.description,
        "is_default": t.is_default, "items": items, "item_count": len(items),
    }


def _own_template(template_id: int, current_user, db) -> models.ClassificationTemplate:
    t = (
        db.query(models.ClassificationTemplate)
        .filter(models.ClassificationTemplate.id == template_id,
                models.ClassificationTemplate.organization_id == current_user.organization_id)
        .first()
    )
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")
    return t


class TemplateIn(BaseModel):
    name: str
    description: Optional[str] = None
    items: list[dict] = []
    is_default: bool = False


@router.get("/templates")
async def list_templates(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(models.ClassificationTemplate)
        .filter(models.ClassificationTemplate.organization_id == current_user.organization_id)
        .order_by(models.ClassificationTemplate.name)
        .all()
    )
    return {"templates": [_to_dict(t) for t in rows]}


@router.post("/templates")
async def create_template(
    body: TemplateIn,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    t = models.ClassificationTemplate(
        organization_id=current_user.organization_id,
        name=body.name, description=body.description,
        data=json.dumps(validate_items(body.items)),
        is_default=body.is_default, created_by=current_user.id,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return _to_dict(t)


@router.post("/templates/seed")
async def seed_default(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create the built-in 'Standard classifications' template for this org."""
    tpl = default_template()
    t = models.ClassificationTemplate(
        organization_id=current_user.organization_id,
        name=tpl["name"], description=tpl["description"],
        data=json.dumps(tpl["items"]), is_default=True, created_by=current_user.id,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return _to_dict(t)


@router.put("/templates/{template_id}")
async def update_template(
    template_id: int,
    body: TemplateIn,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    t = _own_template(template_id, current_user, db)
    t.name, t.description, t.is_default = body.name, body.description, body.is_default
    t.data = json.dumps(validate_items(body.items))
    db.commit()
    db.refresh(t)
    return _to_dict(t)


@router.delete("/templates/{template_id}")
async def delete_template(
    template_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db.delete(_own_template(template_id, current_user, db))
    db.commit()
    return {"deleted": template_id}


@router.post("/templates/{template_id}/apply/{project_id}")
async def apply_template(
    template_id: int,
    project_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create Condition rows on a project from a template's classifications."""
    t = _own_template(template_id, current_user, db)
    project = (
        db.query(models.Project)
        .filter(models.Project.id == project_id,
                models.Project.organization_id == current_user.organization_id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        items = json.loads(t.data) if t.data else []
    except (json.JSONDecodeError, TypeError):
        items = []

    created = 0
    for kwargs in items_to_conditions(items, project_id):
        db.add(models.Condition(**kwargs))
        created += 1
    db.commit()
    return {"project_id": project_id, "conditions_created": created}
