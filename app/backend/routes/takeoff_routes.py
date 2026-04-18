from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
import schemas
import models
from auth import get_current_user
from database import get_db
import json
from datetime import datetime, timezone

router = APIRouter(prefix="/takeoff", tags=["Takeoff & AI"])

@router.post("/drawings/{drawing_id}/results", response_model=schemas.TakeoffResult)
async def save_detection_results(
    drawing_id: int,
    result_data: schemas.TakeoffResultCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Verify drawing access
    drawing = db.query(models.Drawing).join(models.Project).filter(
        models.Drawing.id == drawing_id,
        models.Project.organization_id == current_user.organization_id
    ).first()
    
    if not drawing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Drawing not found"
        )
    
    # Create takeoff result
    db_result = models.TakeoffResult(
        drawing_id=drawing_id,
        detection_data=result_data.detection_data,
        quantities_data=result_data.quantities_data,
        confidence_scores=result_data.confidence_scores,
        processing_time_ms=result_data.processing_time_ms,
        ai_model_version="mock_v1.0"
    )
    db.add(db_result)
    
    # Update drawing status
    drawing.processing_status = models.ProcessingStatus.COMPLETED
    drawing.processed_at = datetime.now(timezone.utc)
    
    db.commit()
    db.refresh(db_result)
    
    return db_result

@router.get("/drawings/{drawing_id}/results")
async def get_detection_results(
    drawing_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Verify drawing access
    drawing = db.query(models.Drawing).join(models.Project).filter(
        models.Drawing.id == drawing_id,
        models.Project.organization_id == current_user.organization_id
    ).first()
    
    if not drawing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Drawing not found"
        )
    
    # Get latest result
    result = db.query(models.TakeoffResult).filter(
        models.TakeoffResult.drawing_id == drawing_id
    ).order_by(models.TakeoffResult.created_at.desc()).first()
    
    if not result:
        return {"message": "No AI results yet", "drawing_id": drawing_id}
    
    return result

@router.get("/projects/{project_id}/results")
async def get_project_results(
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
    
    # Get all drawings with their latest results
    drawings = db.query(models.Drawing).filter(
        models.Drawing.project_id == project_id
    ).all()
    
    results = []
    for drawing in drawings:
        result = db.query(models.TakeoffResult).filter(
            models.TakeoffResult.drawing_id == drawing.id
        ).order_by(models.TakeoffResult.created_at.desc()).first()
        
        if result:
            results.append({
                "drawing": drawing,
                "result": result
            })
    
    return results


