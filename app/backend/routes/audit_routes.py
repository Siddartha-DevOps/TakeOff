"""
TakeOff.ai — activity/audit log (read).

Org-scoped feed of recorded actions (audit.record_activity writes them across the
app). Read-only here; org-isolated.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

import models
from audit import activity_to_dict
from auth import get_current_user
from database import get_db

router = APIRouter(prefix="/activity", tags=["Activity"])


@router.get("")
async def list_activity(
    limit: int = Query(100, ge=1, le=500),
    action: Optional[str] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Recent activity for the caller's organization, newest first."""
    q = db.query(models.ActivityLog).filter(
        models.ActivityLog.organization_id == current_user.organization_id)
    if action:
        q = q.filter(models.ActivityLog.action == action)
    rows = q.order_by(models.ActivityLog.created_at.desc()).limit(limit).all()
    return {"activity": [activity_to_dict(r) for r in rows]}
