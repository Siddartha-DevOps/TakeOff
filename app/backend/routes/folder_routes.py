"""
TakeOff.ai — Drawing folders
Closes the Togal-parity gap "Project folders & organization — color-coded,
folders, sets" (previously not surfaced at all: no folder concept existed,
drawings were a flat per-project list).

Folders are project-scoped and flat (no nesting — see models.DrawingFolder's
docstring for why). Assigning a drawing to a folder is a separate endpoint
from folder CRUD, mirroring how condition assignment (routes/takeoff_routes.py)
is separate from condition CRUD (condition_routes.py) — moving a drawing is a
Drawing-scoped write, not a Folder-scoped one.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models
import schemas
from auth import get_current_user
from database import get_db

router = APIRouter(tags=["Drawing Folders"])


def _get_project(project_id: int, current_user: models.User, db: Session) -> models.Project:
    project = db.query(models.Project).filter(
        models.Project.id == project_id,
        models.Project.organization_id == current_user.organization_id,
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _get_folder(folder_id: int, current_user: models.User, db: Session) -> models.DrawingFolder:
    folder = db.query(models.DrawingFolder).join(models.Project).filter(
        models.DrawingFolder.id == folder_id,
        models.Project.organization_id == current_user.organization_id,
    ).first()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    return folder


def _get_drawing(drawing_id: int, current_user: models.User, db: Session) -> models.Drawing:
    drawing = db.query(models.Drawing).join(models.Project).filter(
        models.Drawing.id == drawing_id,
        models.Project.organization_id == current_user.organization_id,
    ).first()
    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")
    return drawing


@router.get("/projects/{project_id}/folders", response_model=List[schemas.DrawingFolder])
async def list_folders(
    project_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_project(project_id, current_user, db)
    return db.query(models.DrawingFolder).filter(
        models.DrawingFolder.project_id == project_id
    ).order_by(models.DrawingFolder.sort_order, models.DrawingFolder.name).all()


@router.post("/projects/{project_id}/folders", response_model=schemas.DrawingFolder)
async def create_folder(
    project_id: int,
    payload: schemas.DrawingFolderCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_project(project_id, current_user, db)
    folder = models.DrawingFolder(project_id=project_id, **payload.model_dump())
    db.add(folder)
    db.commit()
    db.refresh(folder)
    return folder


@router.put("/folders/{folder_id}", response_model=schemas.DrawingFolder)
async def update_folder(
    folder_id: int,
    payload: schemas.DrawingFolderUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    folder = _get_folder(folder_id, current_user, db)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(folder, field, value)
    db.commit()
    db.refresh(folder)
    return folder


@router.delete("/folders/{folder_id}")
async def delete_folder(
    folder_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # ondelete="SET NULL" on Drawing.folder_id (models.py) handles the DB
    # side; the drawings themselves are never touched or deleted here.
    folder = _get_folder(folder_id, current_user, db)
    db.delete(folder)
    db.commit()
    return {"status": "deleted", "folder_id": folder_id}


@router.put("/drawings/{drawing_id}/folder", response_model=schemas.Drawing)
async def assign_drawing_folder(
    drawing_id: int,
    payload: schemas.DrawingFolderAssign,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    drawing = _get_drawing(drawing_id, current_user, db)
    if payload.folder_id is not None:
        folder = _get_folder(payload.folder_id, current_user, db)
        if folder.project_id != drawing.project_id:
            raise HTTPException(status_code=400, detail="Folder belongs to a different project")
    drawing.folder_id = payload.folder_id
    db.commit()
    db.refresh(drawing)
    return drawing
