import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy.orm import Session

import auth
import models
import realtime
from auth import get_current_user
from database import get_db, SessionLocal

router = APIRouter(tags=["Real-time Collaboration"])

# Real-time collaboration — memory/TOGAL_PARITY_REAUDIT.md #16. See
# realtime.py's module docstring for the Liveblocks/Yjs scope decision.
# WebSocket (/ws/projects/{id}) carries presence + live cursors + comment
# *notifications* only; comments themselves are created/resolved through
# plain REST (/collab/...) so a create has a normal HTTP success/failure
# response instead of a fire-and-forget message, and are then broadcast to
# connected clients over the same WebSocket channel.


def _get_project(project_id: int, current_user: models.User, db: Session) -> models.Project:
    project = db.query(models.Project).filter(
        models.Project.id == project_id,
        models.Project.organization_id == current_user.organization_id,
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _presence_entry(user: models.User, drawing_id: Optional[int] = None, x: Optional[float] = None, y: Optional[float] = None) -> dict:
    return {
        "user_id": user.id,
        "name": user.full_name or user.email,
        "email": user.email,
        "color": realtime.color_for_user(user.id),
        "drawing_id": drawing_id,
        "x": x,
        "y": y,
    }


async def _authenticate_ws(websocket: WebSocket, project_id: int) -> Optional[models.User]:
    token = websocket.query_params.get("token")
    if not token:
        return None
    payload = auth.decode_token(token)
    if payload is None:
        return None
    email = payload.get("sub")
    if not email:
        return None
    db = SessionLocal()
    try:
        user = db.query(models.User).filter(models.User.email == email).first()
        if not user:
            return None
        project = db.query(models.Project).filter(
            models.Project.id == project_id,
            models.Project.organization_id == user.organization_id,
        ).first()
        if not project:
            return None
        return user
    finally:
        db.close()


@router.websocket("/ws/projects/{project_id}")
async def project_presence_socket(websocket: WebSocket, project_id: int):
    user = await _authenticate_ws(websocket, project_id)
    if user is None:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    await realtime.hub.connect(project_id, user.id, websocket)

    join_presence = _presence_entry(user)
    await realtime.hub.touch_presence(project_id, user.id, join_presence)

    # Send the direct reply *before* publishing "user_joined" — publish()
    # is a Redis round-trip our own pubsub listener task is subscribed to,
    # so if it went first, that self-published event could race the
    # explicit send below and arrive first, handing the new connection a
    # "user_joined" as its very first message instead of "presence_sync".
    current_users = await realtime.hub.snapshot_presence(project_id)
    await websocket.send_text(json.dumps({"type": "presence_sync", "users": current_users}))
    await realtime.hub.publish(project_id, {"type": "user_joined", "user": join_presence}, exclude_user_id=user.id)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if msg.get("type") != "cursor":
                continue  # comments go through REST; anything else is ignored
            drawing_id = msg.get("drawing_id")
            x, y = msg.get("x"), msg.get("y")
            if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
                continue
            presence = _presence_entry(user, drawing_id=drawing_id, x=x, y=y)
            await realtime.hub.touch_presence(project_id, user.id, presence)
            await realtime.hub.publish(project_id, {"type": "cursor", **presence}, exclude_user_id=user.id)
    except WebSocketDisconnect:
        pass
    finally:
        await realtime.hub.disconnect(project_id, user.id)
        await realtime.hub.publish(project_id, {"type": "user_left", "user_id": user.id}, exclude_user_id=user.id)


# ── REST: comments (durable) ────────────────────────────────────────────

collab_router = APIRouter(prefix="/collab", tags=["Real-time Collaboration"])


@collab_router.get("/projects/{project_id}/comments")
async def list_comments(
    project_id: int,
    drawing_id: Optional[int] = None,
    include_resolved: bool = True,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_project(project_id, current_user, db)
    q = db.query(models.Comment).filter(models.Comment.project_id == project_id)
    if drawing_id is not None:
        q = q.filter(models.Comment.drawing_id == drawing_id)
    if not include_resolved:
        q = q.filter(models.Comment.resolved.is_(False))
    comments = q.order_by(models.Comment.created_at.asc()).all()
    return {"comments": [realtime.comment_to_dict(c) for c in comments]}


class CommentCreate(BaseModel):
    drawing_id: int
    x: float
    y: float
    body: str
    parent_id: Optional[int] = None


@collab_router.post("/projects/{project_id}/comments")
async def create_comment(
    project_id: int,
    payload: CommentCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = _get_project(project_id, current_user, db)
    if not payload.body.strip():
        raise HTTPException(status_code=400, detail="Comment body cannot be empty")
    drawing = db.query(models.Drawing).filter(
        models.Drawing.id == payload.drawing_id, models.Drawing.project_id == project.id,
    ).first()
    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found in this project")
    if payload.parent_id is not None:
        parent = db.query(models.Comment).filter(
            models.Comment.id == payload.parent_id, models.Comment.project_id == project.id,
        ).first()
        if not parent:
            raise HTTPException(status_code=404, detail="Parent comment not found")

    comment = models.Comment(
        project_id=project.id, drawing_id=payload.drawing_id, parent_id=payload.parent_id,
        x=payload.x, y=payload.y, body=payload.body.strip(), author_id=current_user.id,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)

    result = realtime.comment_to_dict(comment)
    await realtime.hub.publish(project_id, {"type": "comment_created", "comment": result}, exclude_user_id=current_user.id)
    return result


class CommentResolve(BaseModel):
    resolved: bool = True


@collab_router.patch("/comments/{comment_id}/resolve")
async def resolve_comment(
    comment_id: int,
    payload: CommentResolve,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    comment = db.query(models.Comment).filter(models.Comment.id == comment_id).first()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    project = _get_project(comment.project_id, current_user, db)

    comment.resolved = payload.resolved
    comment.resolved_by = current_user.id if payload.resolved else None
    comment.resolved_at = datetime.now(timezone.utc) if payload.resolved else None
    db.commit()
    db.refresh(comment)

    result = realtime.comment_to_dict(comment)
    await realtime.hub.publish(project.id, {"type": "comment_resolved", "comment": result}, exclude_user_id=current_user.id)
    return result


@collab_router.delete("/comments/{comment_id}")
async def delete_comment(
    comment_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    comment = db.query(models.Comment).filter(models.Comment.id == comment_id).first()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    project = _get_project(comment.project_id, current_user, db)
    if comment.author_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the comment's author can delete it")

    db.query(models.Comment).filter(models.Comment.parent_id == comment.id).update({"parent_id": None})
    db.delete(comment)
    db.commit()

    await realtime.hub.publish(project.id, {"type": "comment_deleted", "comment_id": comment_id}, exclude_user_id=current_user.id)
    return {"deleted": True}
