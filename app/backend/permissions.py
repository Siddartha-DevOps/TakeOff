"""
TakeOff.ai — RBAC: role ranking + FastAPI dependency + project-level
permission rule. Closes memory/TOGAL_PARITY_REAUDIT.md #17's "permissions"
half (routes/team_routes.py covers "teams"/"invites").

Centralizes what used to not exist at all: every route in this codebase
that checks authorization does it inline (`Project.organization_id ==
current_user.organization_id`, repeated ~28 times across 11 route files —
confirmed by grep before writing this) with no role concept whatsoever, so
today ANY user in an org has full CRUD on EVERY project in that org
regardless of who created it. This module is deliberately small — it only
adds what's needed to close that gap and gate team management, not a
general-purpose policy engine.
"""

from fastapi import Depends, HTTPException, status

import models
from auth import get_current_user

_ROLE_RANK = {
    models.UserRole.VIEWER: 0,
    models.UserRole.MEMBER: 1,
    models.UserRole.ADMIN: 2,
    models.UserRole.OWNER: 3,
}


def role_at_least(user: models.User, minimum: models.UserRole) -> bool:
    return _ROLE_RANK[user.role] >= _ROLE_RANK[minimum]


def require_role(minimum: models.UserRole):
    """FastAPI dependency: 403s unless current_user.role >= minimum."""
    def _dependency(current_user: models.User = Depends(get_current_user)) -> models.User:
        if not role_at_least(current_user, minimum):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires {minimum.value} role or higher",
            )
        return current_user
    return _dependency


def can_modify_project(user: models.User, project: "models.Project") -> bool:
    """
    ADMIN/OWNER can edit or delete any project in the org. MEMBER can only
    edit/delete projects they themselves created (Project.owner_id) — the
    exact distinction the pre-RBAC code never made. VIEWER can't modify
    anything.
    """
    if role_at_least(user, models.UserRole.ADMIN):
        return True
    return user.role == models.UserRole.MEMBER and project.owner_id == user.id
