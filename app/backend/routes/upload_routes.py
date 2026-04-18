from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import List, Optional
import schemas
import models
from auth import get_current_user
from database import get_db
import aiofiles
import os
from pathlib import Path
import uuid
from datetime import datetime, timezone

router = APIRouter(prefix="/uploads", tags=["Uploads"])

# Upload directory
UPLOAD_DIR = Path(__file__).parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "tiff", "tif"}

def get_file_extension(filename: str) -> str:
    return filename.rsplit(".", 1)[1].lower() if "." in filename else ""

def is_allowed_file(filename: str) -> bool:
    return get_file_extension(filename) in ALLOWED_EXTENSIONS

@router.post("/project/{project_id}/drawings", response_model=schemas.Drawing)
async def upload_drawing(
    project_id: int,
    file: UploadFile = File(...),
    sheet_name: Optional[str] = Form(None),
    scale: Optional[str] = Form(None),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Verify project access
    project = db.query(models.Project).filter(
        models.Project.id == project_id,
        models.Project.organization_id == current_user.organization_id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    # Validate file
    if not is_allowed_file(file.filename):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type not allowed. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}"
        )
    
    # Generate unique filename
    file_ext = get_file_extension(file.filename)
    unique_filename = f"{uuid.uuid4()}.{file_ext}"
    file_path = UPLOAD_DIR / str(project_id)
    file_path.mkdir(exist_ok=True)
    full_path = file_path / unique_filename
    
    # Save file
    try:
        async with aiofiles.open(full_path, 'wb') as f:
            content = await file.read()
            await f.write(content)
        
        file_size = len(content)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save file: {str(e)}"
        )
    
    # Create database record
    db_drawing = models.Drawing(
        project_id=project_id,
        filename=unique_filename,
        original_filename=file.filename,
        file_path=str(full_path),
        file_size=file_size,
        file_type=file_ext.upper(),
        sheet_name=sheet_name,
        scale=scale,
        processing_status=models.ProcessingStatus.PENDING
    )
    db.add(db_drawing)
    db.commit()
    db.refresh(db_drawing)
    
    return db_drawing

@router.get("/project/{project_id}/drawings", response_model=List[schemas.Drawing])
async def list_project_drawings(
    project_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Verify project access
    project = db.query(models.Project).filter(
        models.Project.id == project_id,
        models.Project.organization_id == current_user.organization_id
    ).first()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )
    
    drawings = db.query(models.Drawing).filter(
        models.Drawing.project_id == project_id
    ).all()
    
    return drawings

@router.get("/drawings/{drawing_id}", response_model=schemas.Drawing)
async def get_drawing(
    drawing_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    drawing = db.query(models.Drawing).join(models.Project).filter(
        models.Drawing.id == drawing_id,
        models.Project.organization_id == current_user.organization_id
    ).first()
    
    if not drawing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Drawing not found"
        )
    
    return drawing

@router.get("/drawings/{drawing_id}/file")
async def download_drawing_file(
    drawing_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    from fastapi.responses import FileResponse
    import os
    
    drawing = db.query(models.Drawing).join(models.Project).filter(
        models.Drawing.id == drawing_id,
        models.Project.organization_id == current_user.organization_id
    ).first()
    
    if not drawing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Drawing not found"
        )
    
    if not os.path.exists(drawing.file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found on server"
        )
    
    return FileResponse(
        path=drawing.file_path,
        media_type=f'image/{drawing.file_type.lower()}' if drawing.file_type != 'PDF' else 'application/pdf',
        filename=drawing.original_filename
    )