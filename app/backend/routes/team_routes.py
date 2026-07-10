import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

import models
import permissions
from auth import create_access_token, get_current_user, get_password_hash
from database import get_db

router = APIRouter(prefix="/team", tags=["Team"])

# Teams/roles/permissions/invites — memory/TOGAL_PARITY_REAUDIT.md #17.
# See permissions.py for the role-rank/CRUD-gating half of this gap.

INVITE_TTL_DAYS = 7
_INVITABLE_ROLES = {"admin", "member", "viewer"}  # OWNER is never granted via invite — see POST /invites


def _member_dict(u: "models.User") -> dict:
    return {
        "id": u.id, "email": u.email, "full_name": u.full_name,
        "role": u.role.value, "is_active": u.is_active, "created_at": u.created_at,
    }


def _invite_dict(inv: "models.Invite") -> dict:
    return {
        "id": inv.id, "email": inv.email, "role": inv.role.value, "status": inv.status.value,
        "token": inv.token, "expires_at": inv.expires_at, "created_at": inv.created_at,
    }


@router.get("/members")
async def list_members(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    members = db.query(models.User).filter(
        models.User.organization_id == current_user.organization_id,
    ).order_by(models.User.created_at.asc()).all()
    return {"members": [_member_dict(m) for m in members]}


class RoleUpdate(BaseModel):
    role: Literal["owner", "admin", "member", "viewer"]


@router.patch("/members/{user_id}/role")
async def update_member_role(
    user_id: int,
    payload: RoleUpdate,
    current_user: models.User = Depends(permissions.require_role(models.UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    target = db.query(models.User).filter(
        models.User.id == user_id, models.User.organization_id == current_user.organization_id,
    ).first()
    if not target:
        raise HTTPException(status_code=404, detail="Member not found")

    new_role = models.UserRole(payload.role)

    # Only an OWNER can grant or revoke OWNER — an ADMIN promoting someone
    # to OWNER (or demoting an existing OWNER) would be granting privileges
    # equal to or above their own, which no role should be able to do to
    # itself or others.
    if (new_role == models.UserRole.OWNER or target.role == models.UserRole.OWNER) and current_user.role != models.UserRole.OWNER:
        raise HTTPException(status_code=403, detail="Only an owner can grant or change owner status")

    if target.role == models.UserRole.OWNER and new_role != models.UserRole.OWNER:
        remaining_owners = db.query(models.User).filter(
            models.User.organization_id == current_user.organization_id,
            models.User.role == models.UserRole.OWNER,
            models.User.id != target.id,
        ).count()
        if remaining_owners == 0:
            raise HTTPException(status_code=400, detail="Cannot demote the organization's last owner")

    target.role = new_role
    db.commit()
    db.refresh(target)
    return _member_dict(target)


@router.delete("/members/{user_id}")
async def remove_member(
    user_id: int,
    current_user: models.User = Depends(permissions.require_role(models.UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot remove yourself from the team")

    target = db.query(models.User).filter(
        models.User.id == user_id, models.User.organization_id == current_user.organization_id,
    ).first()
    if not target:
        raise HTTPException(status_code=404, detail="Member not found")

    if target.role == models.UserRole.OWNER and current_user.role != models.UserRole.OWNER:
        raise HTTPException(status_code=403, detail="Only an owner can remove an owner")

    if target.role == models.UserRole.OWNER:
        remaining_owners = db.query(models.User).filter(
            models.User.organization_id == current_user.organization_id,
            models.User.role == models.UserRole.OWNER,
            models.User.id != target.id,
        ).count()
        if remaining_owners == 0:
            raise HTTPException(status_code=400, detail="Cannot remove the organization's last owner")

    # Deactivate rather than hard-delete: target.id is referenced by FKs
    # across most of the app (Project.owner_id, CorrectionEvent.user_id,
    # Comment.author_id, HandoffAuditEvent.user_id, ...) — a real delete
    # would either cascade-destroy that history or fail outright. Removing
    # someone from the team should end their access, not erase the record
    # of what they did.
    target.is_active = False
    db.commit()
    return {"removed": True}


@router.get("/invites")
async def list_invites(
    current_user: models.User = Depends(permissions.require_role(models.UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    invites = db.query(models.Invite).filter(
        models.Invite.organization_id == current_user.organization_id,
    ).order_by(models.Invite.created_at.desc()).all()
    now = datetime.now(timezone.utc)
    for inv in invites:
        if inv.status == models.InviteStatus.PENDING and inv.expires_at < now:
            inv.status = models.InviteStatus.EXPIRED
    db.commit()
    return {"invites": [_invite_dict(inv) for inv in invites]}


class InviteCreate(BaseModel):
    email: EmailStr
    role: Literal["admin", "member", "viewer"]


@router.post("/invites")
async def create_invite(
    payload: InviteCreate,
    current_user: models.User = Depends(permissions.require_role(models.UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    existing_user = db.query(models.User).filter(models.User.email == payload.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="A user with this email already has an account")

    # Re-use (refresh) any existing pending invite for this email in this
    # org instead of piling up duplicates every time someone clicks
    # "resend".
    invite = db.query(models.Invite).filter(
        models.Invite.organization_id == current_user.organization_id,
        models.Invite.email == payload.email,
        models.Invite.status == models.InviteStatus.PENDING,
    ).first()

    if invite is None:
        invite = models.Invite(
            organization_id=current_user.organization_id, email=payload.email,
            invited_by=current_user.id, token=secrets.token_urlsafe(32),
        )
        db.add(invite)

    invite.role = models.UserRole(payload.role)
    invite.status = models.InviteStatus.PENDING
    invite.expires_at = datetime.now(timezone.utc) + timedelta(days=INVITE_TTL_DAYS)
    db.commit()
    db.refresh(invite)
    return _invite_dict(invite)


@router.delete("/invites/{invite_id}")
async def revoke_invite(
    invite_id: int,
    current_user: models.User = Depends(permissions.require_role(models.UserRole.ADMIN)),
    db: Session = Depends(get_db),
):
    invite = db.query(models.Invite).filter(
        models.Invite.id == invite_id, models.Invite.organization_id == current_user.organization_id,
    ).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")
    if invite.status != models.InviteStatus.PENDING:
        raise HTTPException(status_code=400, detail=f"Invite is already {invite.status.value}")

    invite.status = models.InviteStatus.REVOKED
    db.commit()
    return {"revoked": True}


# ── Public: accept-invite flow (no auth — the recipient has no account yet) ──

@router.get("/invites/{token}/preview")
async def preview_invite(token: str, db: Session = Depends(get_db)):
    invite = db.query(models.Invite).filter(models.Invite.token == token).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")
    if invite.status == models.InviteStatus.PENDING and invite.expires_at < datetime.now(timezone.utc):
        invite.status = models.InviteStatus.EXPIRED
        db.commit()
    if invite.status != models.InviteStatus.PENDING:
        raise HTTPException(status_code=410, detail=f"This invite is {invite.status.value}")

    org = db.query(models.Organization).filter(models.Organization.id == invite.organization_id).first()
    return {
        "email": invite.email, "role": invite.role.value,
        "organization_name": org.name if org else "Organization",
        "expires_at": invite.expires_at,
    }


class InviteAccept(BaseModel):
    full_name: str
    password: str


@router.post("/invites/{token}/accept")
async def accept_invite(token: str, payload: InviteAccept, db: Session = Depends(get_db)):
    invite = db.query(models.Invite).filter(models.Invite.token == token).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")
    if invite.status == models.InviteStatus.PENDING and invite.expires_at < datetime.now(timezone.utc):
        invite.status = models.InviteStatus.EXPIRED
        db.commit()
    if invite.status != models.InviteStatus.PENDING:
        raise HTTPException(status_code=410, detail=f"This invite is {invite.status.value}")

    if db.query(models.User).filter(models.User.email == invite.email).first():
        raise HTTPException(status_code=400, detail="A user with this email already has an account")
    if not payload.password or len(payload.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    user = models.User(
        email=invite.email, full_name=payload.full_name,
        hashed_password=get_password_hash(payload.password),
        organization_id=invite.organization_id, role=invite.role,
    )
    db.add(user)
    invite.status = models.InviteStatus.ACCEPTED
    invite.accepted_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)

    access_token = create_access_token(data={"sub": user.email})
    return {"access_token": access_token, "token_type": "bearer", "user": _member_dict(user)}
