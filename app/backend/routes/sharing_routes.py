"""
TakeOff.ai — external collaboration (share a project with people who have no account).

Org members create tokenized share links (view / comment); guests open
`/shared/{token}` with no login and see the project read-only. Mirrors Togal's
"collaborate with users outside your account."

- POST   /api/projects/{project_id}/shares   create a share link (auth)
- GET    /api/projects/{project_id}/shares    list this project's shares (auth)
- DELETE /api/shares/{share_id}               revoke a share (auth)
- GET    /api/shared/{token}                   PUBLIC — resolve a share, read-only

Token/validity/permission logic is pure (sharing.py); this layer is DB I/O.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

import models
from auth import get_current_user
from database import get_db
from sharing import new_share_token, normalize_role, share_is_valid

router = APIRouter(tags=["Sharing"])


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


def _share_to_dict(share: models.ProjectShare) -> dict:
    return {
        "id": share.id,
        "project_id": share.project_id,
        "email": share.email,
        "role": share.role,
        "revoked": share.revoked,
        "expires_at": share.expires_at.isoformat() if share.expires_at else None,
        "created_at": share.created_at.isoformat() if share.created_at else None,
        "token": share.token,                       # owner sees it to copy the link
        "path": f"/shared/{share.token}",           # frontend builds the absolute URL
    }


class ShareRequest(BaseModel):
    email: Optional[str] = None
    role: str = "viewer"
    expires_in_days: Optional[int] = None


@router.post("/projects/{project_id}/shares")
async def create_share(
    project_id: int,
    body: ShareRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create an account-free share link for a project."""
    _require_project(project_id, current_user, db)
    expires_at = None
    if body.expires_in_days and body.expires_in_days > 0:
        expires_at = datetime.now(timezone.utc) + timedelta(days=body.expires_in_days)
    share = models.ProjectShare(
        project_id=project_id,
        organization_id=current_user.organization_id,
        token=new_share_token(),
        email=body.email,
        role=normalize_role(body.role),
        expires_at=expires_at,
        created_by=current_user.id,
    )
    db.add(share)
    db.commit()
    db.refresh(share)
    return _share_to_dict(share)


@router.get("/projects/{project_id}/shares")
async def list_shares(
    project_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_project(project_id, current_user, db)
    shares = (
        db.query(models.ProjectShare)
        .filter(models.ProjectShare.project_id == project_id)
        .order_by(models.ProjectShare.created_at.desc())
        .all()
    )
    return {"shares": [_share_to_dict(s) for s in shares]}


@router.delete("/shares/{share_id}")
async def revoke_share(
    share_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Revoke a share (kills the link immediately)."""
    share = (
        db.query(models.ProjectShare)
        .filter(models.ProjectShare.id == share_id,
                models.ProjectShare.organization_id == current_user.organization_id)
        .first()
    )
    if not share:
        raise HTTPException(status_code=404, detail="Share not found")
    share.revoked = True
    db.commit()
    return {"revoked": share_id}


@router.get("/shared/{token}")
async def resolve_share(token: str, db: Session = Depends(get_db)):
    """PUBLIC — resolve a share token into a read-only project view (no auth).

    Returns 404 for unknown/revoked/expired tokens so links can't be probed for
    validity beyond "works or doesn't".
    """
    share = (
        db.query(models.ProjectShare)
        .filter(models.ProjectShare.token == token)
        .first()
    )
    if not share or not share_is_valid(revoked=share.revoked, expires_at=share.expires_at):
        raise HTTPException(status_code=404, detail="This share link is invalid or has expired")

    share.last_accessed_at = datetime.now(timezone.utc)
    db.commit()

    project = db.query(models.Project).filter(models.Project.id == share.project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project no longer exists")
    drawings = (
        db.query(models.Drawing)
        .filter(models.Drawing.project_id == project.id)
        .all()
    )
    return {
        "role": share.role,
        "project": {"id": project.id, "name": project.name, "description": project.description},
        "sheets": [
            {"id": d.id, "sheet_name": d.sheet_name or d.original_filename,
             "sheet_number": d.sheet_number, "discipline": d.discipline}
            for d in drawings
        ],
    }
