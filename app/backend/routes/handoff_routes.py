from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timezone

import models
import handoff_engine
from auth import get_current_user
from database import get_db

router = APIRouter(prefix="/handoff", tags=["Estimating Handoff"])

# Estimating-handoff integration: quantities -> UPC/WBS map + audit trail —
# memory/TOGAL_PARITY_REAUDIT.md #15. See handoff_engine.py's module
# docstring for the Procore/Ediphi/DESTINI column-layout sourcing and why
# this is a structured file handoff rather than a live API push.

_VALID_TARGET_SYSTEMS = {s.value for s in models.HandoffTargetSystem}


def _get_project(project_id: int, current_user: models.User, db: Session) -> models.Project:
    project = db.query(models.Project).filter(
        models.Project.id == project_id,
        models.Project.organization_id == current_user.organization_id,
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _parse_drawing_ids(drawing_ids: Optional[str]) -> Optional[list]:
    if not drawing_ids:
        return None
    try:
        return [int(x) for x in drawing_ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="drawing_ids must be a comma-separated list of integers")


@router.get("/projects/{project_id}/mappings")
async def list_mappings(
    project_id: int,
    drawing_ids: Optional[str] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = _get_project(project_id, current_user, db)
    return {"rows": handoff_engine.get_mapping_status(db, project, _parse_drawing_ids(drawing_ids))}


class MappingUpsert(BaseModel):
    trade: str
    item: str
    wbs_code: Optional[str] = None
    upc_code: Optional[str] = None
    description: Optional[str] = None
    target_system: str = "generic"


@router.put("/projects/{project_id}/mappings")
async def upsert_mapping(
    project_id: int,
    payload: MappingUpsert,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = _get_project(project_id, current_user, db)
    if payload.target_system not in _VALID_TARGET_SYSTEMS:
        raise HTTPException(status_code=400, detail=f"target_system must be one of: {sorted(_VALID_TARGET_SYSTEMS)}")
    mapping = handoff_engine.upsert_mapping(
        db, project, current_user, payload.trade, payload.item,
        payload.wbs_code, payload.upc_code, payload.description, payload.target_system,
    )
    return {
        "id": mapping.id, "trade": mapping.trade, "item": mapping.item,
        "wbs_code": mapping.wbs_code, "upc_code": mapping.upc_code,
        "description": mapping.description, "target_system": mapping.target_system.value,
    }


class BulkMappingUpsert(BaseModel):
    mappings: List[MappingUpsert]


@router.put("/projects/{project_id}/mappings/bulk")
async def bulk_upsert_mappings(
    project_id: int,
    payload: BulkMappingUpsert,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = _get_project(project_id, current_user, db)
    for m in payload.mappings:
        if m.target_system not in _VALID_TARGET_SYSTEMS:
            raise HTTPException(status_code=400, detail=f"target_system must be one of: {sorted(_VALID_TARGET_SYSTEMS)}")
    saved = [
        handoff_engine.upsert_mapping(db, project, current_user, m.trade, m.item, m.wbs_code, m.upc_code, m.description, m.target_system)
        for m in payload.mappings
    ]
    return {"saved": len(saved)}


@router.delete("/mappings/{mapping_id}")
async def delete_mapping(
    mapping_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    mapping = db.query(models.CostCodeMapping).filter(models.CostCodeMapping.id == mapping_id).first()
    if not mapping:
        raise HTTPException(status_code=404, detail="Mapping not found")
    project = _get_project(mapping.project_id, current_user, db)
    handoff_engine.delete_mapping(db, project, current_user, mapping)
    return {"deleted": True}


@router.get("/projects/{project_id}/audit-trail")
async def get_audit_trail(
    project_id: int,
    limit: int = 100,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = _get_project(project_id, current_user, db)
    events = (
        db.query(models.HandoffAuditEvent)
        .filter(models.HandoffAuditEvent.project_id == project.id)
        .order_by(models.HandoffAuditEvent.created_at.desc())
        .limit(min(limit, 500))
        .all()
    )
    users = {u.id: u for u in db.query(models.User).filter(models.User.id.in_({e.user_id for e in events})).all()} if events else {}
    return {
        "events": [
            {
                "id": e.id,
                "action": e.action,
                "target_system": e.target_system.value if e.target_system else None,
                "before": e.before,
                "after": e.after,
                "user_email": users[e.user_id].email if e.user_id in users else None,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ]
    }


@router.get("/projects/{project_id}/export")
async def export_handoff(
    project_id: int,
    target_system: str = "generic",
    drawing_ids: Optional[str] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = _get_project(project_id, current_user, db)
    if target_system not in _VALID_TARGET_SYSTEMS:
        raise HTTPException(status_code=400, detail=f"target_system must be one of: {sorted(_VALID_TARGET_SYSTEMS)}")

    file, mapped, unmapped = handoff_engine.generate_handoff_export(
        db, project, current_user, target_system, _parse_drawing_ids(drawing_ids),
    )

    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in project.name) or "handoff"
    filename = f"handoff_{target_system}_{safe_name}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"

    return StreamingResponse(
        file,
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "X-Handoff-Mapped-Rows": str(mapped),
            "X-Handoff-Unmapped-Rows": str(unmapped),
        },
    )
