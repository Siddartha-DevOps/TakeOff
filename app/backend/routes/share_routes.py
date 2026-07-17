"""
TakeOff.ai — External collaboration without a TakeOff account.
Closes the Togal-parity gap "External collaboration — unlimited, no
account needed." mockData.js's pricing FAQ already claimed this ("no
TakeOff account required to view") but nothing backed it: every route in
this backend except blog/webhook required a real authenticated User
(confirmed by grepping every routes/*.py file for get_current_user before
writing this). This is that capability, built for real.

Two routers:
  - `router` (authenticated, mounted at /api): create/list/revoke share
    links for a project. A normal org-member action.
  - `guest_router` (NO auth at all, mounted at /api/guest): everything an
    external collaborator can reach with just the link — resolve it,
    view the drawing (file + tiles, mirroring upload_routes.py's
    authenticated equivalents), view takeoff results, list/post comments.

Scope, stated plainly: view + comment only. A guest link can never touch
conditions, uploads, or annotation edits — see models.ShareLink's
docstring for why that boundary is deliberate, not a shortcut.

Tile/file URLs are built with the token as a path segment (not a header)
specifically so they work as plain <img src="..."> / OpenSeadragon
getTileUrl targets in the guest-facing frontend page — a Bearer header,
which every *authenticated* equivalent of these routes requires, cannot
be attached to a plain image request from a browser at all.
"""

import json
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session

import models
import realtime
import schemas
import storage
from auth import get_current_user
from database import get_db

router = APIRouter(tags=["Share Links"])
guest_router = APIRouter(prefix="/guest", tags=["Guest Access"])


# ── Authenticated: manage a project's share links ───────────────────────

def _get_project(project_id: int, current_user: models.User, db: Session) -> models.Project:
    project = db.query(models.Project).filter(
        models.Project.id == project_id,
        models.Project.organization_id == current_user.organization_id,
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.post("/projects/{project_id}/share-links", response_model=schemas.ShareLink)
async def create_share_link(
    project_id: int,
    payload: schemas.ShareLinkCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = _get_project(project_id, current_user, db)
    expires_at = (
        datetime.now(timezone.utc) + timedelta(days=payload.expires_in_days)
        if payload.expires_in_days else None
    )
    link = models.ShareLink(
        project_id=project.id,
        token=secrets.token_urlsafe(32),  # same generation as Invite.token
        permission=models.ShareLinkPermission(payload.permission),
        label=payload.label,
        created_by=current_user.id,
        expires_at=expires_at,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


@router.get("/projects/{project_id}/share-links", response_model=List[schemas.ShareLink])
async def list_share_links(
    project_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_project(project_id, current_user, db)
    return db.query(models.ShareLink).filter(
        models.ShareLink.project_id == project_id
    ).order_by(models.ShareLink.created_at.desc()).all()


@router.delete("/share-links/{link_id}")
async def revoke_share_link(
    link_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    link = db.query(models.ShareLink).join(models.Project).filter(
        models.ShareLink.id == link_id,
        models.Project.organization_id == current_user.organization_id,
    ).first()
    if not link:
        raise HTTPException(status_code=404, detail="Share link not found")
    link.revoked_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "revoked", "share_link_id": link_id}


# ── Guest: token-gated, no auth ──────────────────────────────────────────

def _resolve_link(token: str, db: Session) -> models.ShareLink:
    link = db.query(models.ShareLink).filter(models.ShareLink.token == token).first()
    now = datetime.now(timezone.utc)
    # Identical response whether the token never existed, was revoked, or
    # expired -- never let a guest distinguish "wrong link" from "link was
    # cut off," which would leak that a link used to be valid.
    if not link or link.revoked_at is not None or (link.expires_at is not None and link.expires_at < now):
        raise HTTPException(status_code=404, detail="This share link is invalid or has expired")
    return link


def _get_guest_drawing(token: str, drawing_id: int, db: Session):
    link = _resolve_link(token, db)
    drawing = db.query(models.Drawing).filter(
        models.Drawing.id == drawing_id, models.Drawing.project_id == link.project_id,
    ).first()
    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")
    return link, drawing


@guest_router.get("/{token}", response_model=schemas.GuestProjectInfo)
async def guest_resolve(token: str, db: Session = Depends(get_db)):
    link = _resolve_link(token, db)
    project = db.query(models.Project).filter(models.Project.id == link.project_id).first()
    drawings = db.query(models.Drawing).filter(
        models.Drawing.project_id == project.id
    ).order_by(models.Drawing.page_number, models.Drawing.uploaded_at).all()
    return {
        "project_name": project.name,
        "permission": link.permission.value,
        "drawings": [
            {
                "id": d.id, "sheet_name": d.sheet_name, "sheet_number": d.sheet_number,
                "file_type": d.file_type, "page_number": d.page_number, "total_pages": d.total_pages,
            }
            for d in drawings
        ],
    }


@guest_router.get("/{token}/drawings/{drawing_id}/file")
async def guest_drawing_file(token: str, drawing_id: int, db: Session = Depends(get_db)):
    """Mirrors upload_routes.py's download_drawing_file(), token-gated instead of JWT-gated."""
    _link, drawing = _get_guest_drawing(token, drawing_id, db)

    if storage.is_storage_uri(drawing.file_path):
        if not storage.storage_available():
            raise HTTPException(status_code=503, detail="Object storage isn't configured but this drawing is stored there.")
        key = storage.key_from_uri(drawing.file_path)
        if storage.object_head(key) is None:
            raise HTTPException(status_code=404, detail="File not found in object storage")
        return RedirectResponse(storage.generate_presigned_download(key))

    if not os.path.exists(drawing.file_path):
        raise HTTPException(status_code=404, detail="File not found on server")

    media_type = 'application/pdf' if drawing.file_type == 'PDF' else f'image/{drawing.file_type.lower()}'
    return FileResponse(path=drawing.file_path, media_type=media_type, filename=drawing.original_filename)


@guest_router.get("/{token}/drawings/{drawing_id}/tiles/status")
async def guest_tile_status(token: str, drawing_id: int, db: Session = Depends(get_db)):
    """Mirrors upload_routes.py's get_tile_status()."""
    from tiling import read_tile_meta, tiling_available
    from routes.upload_routes import _tiles_dir

    _link, drawing = _get_guest_drawing(token, drawing_id, db)
    if not tiling_available():
        return {"ready": False, "reason": "Tiling isn't available on the server (Pillow isn't installed)."}
    meta = read_tile_meta(str(_tiles_dir(drawing.project_id, drawing_id)))
    if meta is None:
        return {"ready": False}
    return {"ready": True, **meta}


@guest_router.get("/{token}/drawings/{drawing_id}/tiles/{level}/{tile_filename}")
async def guest_tile(token: str, drawing_id: int, level: int, tile_filename: str, db: Session = Depends(get_db)):
    """Mirrors upload_routes.py's get_tile() -- same filename-shape guard against path traversal."""
    from routes.upload_routes import _tiles_dir

    _link, drawing = _get_guest_drawing(token, drawing_id, db)
    if not re.fullmatch(r"\d+_\d+\.jpg", tile_filename):
        raise HTTPException(status_code=400, detail="Invalid tile filename")
    path = _tiles_dir(drawing.project_id, drawing_id) / str(level) / tile_filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Tile not found")
    return FileResponse(path=str(path), media_type="image/jpeg")


@guest_router.get("/{token}/drawings/{drawing_id}/results")
async def guest_drawing_results(token: str, drawing_id: int, db: Session = Depends(get_db)):
    _link, drawing = _get_guest_drawing(token, drawing_id, db)
    result = db.query(models.TakeoffResult).filter(
        models.TakeoffResult.drawing_id == drawing_id
    ).order_by(models.TakeoffResult.created_at.desc()).first()
    if not result:
        return {"status": "not_ready"}
    return {
        "status": "ready",
        "detection_data": json.loads(result.detection_data) if result.detection_data else None,
        "quantities_data": json.loads(result.quantities_data) if result.quantities_data else None,
    }


@guest_router.get("/{token}/comments")
async def guest_list_comments(token: str, drawing_id: Optional[int] = None, db: Session = Depends(get_db)):
    link = _resolve_link(token, db)
    q = db.query(models.Comment).filter(models.Comment.project_id == link.project_id)
    if drawing_id is not None:
        q = q.filter(models.Comment.drawing_id == drawing_id)
    comments = q.order_by(models.Comment.created_at.asc()).all()
    return {"comments": [realtime.comment_to_dict(c) for c in comments]}


@guest_router.post("/{token}/comments")
async def guest_create_comment(token: str, payload: schemas.GuestCommentCreate, db: Session = Depends(get_db)):
    link = _resolve_link(token, db)
    if link.permission != models.ShareLinkPermission.COMMENT:
        raise HTTPException(status_code=403, detail="This share link is view-only")
    if not payload.body.strip():
        raise HTTPException(status_code=400, detail="Comment body cannot be empty")
    if not payload.guest_name.strip():
        raise HTTPException(status_code=400, detail="Enter your name to comment")

    drawing = db.query(models.Drawing).filter(
        models.Drawing.id == payload.drawing_id, models.Drawing.project_id == link.project_id,
    ).first()
    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found in this project")
    if payload.parent_id is not None:
        parent = db.query(models.Comment).filter(
            models.Comment.id == payload.parent_id, models.Comment.project_id == link.project_id,
        ).first()
        if not parent:
            raise HTTPException(status_code=404, detail="Parent comment not found")

    comment = models.Comment(
        project_id=link.project_id, drawing_id=payload.drawing_id, parent_id=payload.parent_id,
        x=payload.x, y=payload.y, body=payload.body.strip(),
        author_id=None, guest_name=payload.guest_name.strip()[:100], share_link_id=link.id,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)

    result = realtime.comment_to_dict(comment)
    # No exclude_user_id: the guest posting this isn't a WebSocket
    # participant at all (guest_router has no WS auth path), so every
    # connected team member should see it, with nobody to exclude.
    await realtime.hub.publish(link.project_id, {"type": "comment_created", "comment": result})
    return result
