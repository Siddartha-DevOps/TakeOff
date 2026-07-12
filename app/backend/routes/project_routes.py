from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
import schemas
import models
import permissions
import entitlements
from auth import get_current_user
from database import get_db

router = APIRouter(prefix="/projects", tags=["Projects"])

# RBAC — memory/TOGAL_PARITY_REAUDIT.md #17: before this, every route here
# only checked organization_id, so any user in an org (including a VIEWER)
# had full CRUD on every project in it. create/update/delete now go
# through permissions.py; list/get stay open to any org member (VIEWER
# included — read access is the point of that role).

@router.post("", response_model=schemas.Project)
async def create_project(
    project_data: schemas.ProjectCreate,
    current_user: models.User = Depends(permissions.require_role(models.UserRole.MEMBER)),
    db: Session = Depends(get_db)
):
    # Entitlements — memory/TOGAL_PARITY_REAUDIT.md #18. 402, not 403: this
    # isn't a permissions problem (the user IS allowed to create projects),
    # it's a "pay for more" problem — the distinct HTTP status lets the
    # frontend tell the two apart and show an upgrade prompt instead of a
    # generic access-denied message.
    allowed, snapshot = entitlements.check_entitlement(db, current_user.organization_id, "project")
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "message": f"Monthly project limit reached for the {snapshot['plan_label']} plan "
                           f"({snapshot['projects']['used']}/{snapshot['projects']['limit']}). Upgrade to create more projects.",
                "billing": snapshot,
            },
        )

    db_project = models.Project(
        name=project_data.name,
        description=project_data.description,
        project_type=project_data.project_type,
        owner_id=current_user.id,
        organization_id=current_user.organization_id,
        status="active"
    )
    db.add(db_project)
    db.commit()
    db.refresh(db_project)
    return db_project

@router.get("", response_model=List[schemas.ProjectList])
async def list_projects(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    projects = db.query(models.Project).filter(
        models.Project.organization_id == current_user.organization_id
    ).all()
    
    # Add computed fields
    result = []
    for p in projects:
        project_dict = {
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "project_type": p.project_type,
            "owner_id": p.owner_id,
            "organization_id": p.organization_id,
            "status": p.status,
            "created_at": p.created_at,
            "updated_at": p.updated_at,
            "sheets_count": len(p.drawings),
            "progress": 0  # TODO: Calculate based on processing status
        }
        result.append(project_dict)
    
    return result

@router.get("/{project_id}", response_model=schemas.Project)
async def get_project(
    project_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    project = db.query(models.Project).filter(
        models.Project.id == project_id,
        models.Project.organization_id == current_user.organization_id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    return project

@router.put("/{project_id}", response_model=schemas.Project)
async def update_project(
    project_id: int,
    project_data: schemas.ProjectUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    project = db.query(models.Project).filter(
        models.Project.id == project_id,
        models.Project.organization_id == current_user.organization_id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    if not permissions.can_modify_project(current_user, project):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You don't have permission to edit this project")

    # Update fields
    if project_data.name is not None:
        project.name = project_data.name
    if project_data.description is not None:
        project.description = project_data.description
    if project_data.project_type is not None:
        project.project_type = project_data.project_type
    if project_data.status is not None:
        project.status = project_data.status
    
    db.commit()
    db.refresh(project)
    return project

@router.delete("/{project_id}")
async def delete_project(
    project_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    project = db.query(models.Project).filter(
        models.Project.id == project_id,
        models.Project.organization_id == current_user.organization_id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    if not permissions.can_modify_project(current_user, project):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You don't have permission to delete this project")

    db.delete(project)
    db.commit()
    return {"message": "Project deleted successfully"}