"""Tenant-safe processing job status API."""

import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models
from auth import get_current_user
from database import get_db

router = APIRouter(prefix="/jobs", tags=["Processing Jobs"])


def _public(job: models.ProcessingJob) -> dict:
    return {
        "id": job.id,
        "job_type": job.job_type,
        "drawing_id": job.drawing_id,
        "project_id": job.project_id,
        "status": job.status,
        "progress": job.progress,
        "attempt_count": job.attempt_count,
        "max_attempts": job.max_attempts,
        "error": job.error,
        "result": json.loads(job.result_json) if job.result_json else None,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "next_attempt_at": job.next_attempt_at,
        "completed_at": job.completed_at,
        "updated_at": job.updated_at,
    }


@router.get("/{job_id}")
async def get_job(job_id: str, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    job = db.query(models.ProcessingJob).filter(
        models.ProcessingJob.id == job_id,
        models.ProcessingJob.organization_id == current_user.organization_id,
    ).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _public(job)


@router.get("/drawing/{drawing_id}/latest")
async def latest_drawing_jobs(drawing_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    drawing = db.query(models.Drawing).join(models.Project).filter(
        models.Drawing.id == drawing_id,
        models.Project.organization_id == current_user.organization_id,
    ).first()
    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")
    jobs = db.query(models.ProcessingJob).filter(
        models.ProcessingJob.drawing_id == drawing_id,
        models.ProcessingJob.organization_id == current_user.organization_id,
    ).order_by(models.ProcessingJob.created_at.desc()).limit(10).all()
    return [_public(job) for job in jobs]
