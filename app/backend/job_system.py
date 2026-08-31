"""PostgreSQL-tracked Celery orchestration for durable drawing work."""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Callable, Optional

import models
from database import SessionLocal

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = {
    models.JobStatus.QUEUED.value,
    models.JobStatus.RUNNING.value,
    models.JobStatus.RETRYING.value,
}
JOB_TYPES = {"analysis", "tiles"}
STALE_SECONDS = int(os.environ.get("JOB_STALE_SECONDS", "900"))
DEFAULT_MAX_ATTEMPTS = int(os.environ.get("JOB_MAX_ATTEMPTS", "3"))


class RetryableJobError(RuntimeError):
    def __init__(self, message: str, attempt_count: int, max_attempts: int):
        super().__init__(message)
        self.attempt_count = attempt_count
        self.max_attempts = max_attempts


class PermanentJobError(RuntimeError):
    pass


def jobs_disabled() -> bool:
    return os.environ.get("TAKEOFF_DISABLE_BACKGROUND_ANALYSIS", "").lower() in {"1", "true", "yes", "on"}


def celery_configured() -> bool:
    return bool(os.environ.get("REDIS_URL"))


def redis_ready() -> bool:
    if not celery_configured():
        return False
    try:
        import redis
        client = redis.Redis.from_url(
            os.environ["REDIS_URL"],
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        return bool(client.ping())
    except Exception:
        return False


def celery_worker_ready() -> bool:
    """Confirm that at least one Celery worker is consuming this queue."""
    if not celery_configured() or not redis_ready():
        return False
    try:
        from celery_app import celery_app
        return bool(celery_app.control.inspect(timeout=1.0).ping() or {})
    except Exception:
        return False


def queue_backend() -> str:
    return "celery" if celery_configured() else "unavailable"


def retry_delay_seconds(attempt_count: int) -> int:
    return min(300, 15 * (2 ** max(0, int(attempt_count) - 1)))


def _organization_id(db, drawing: models.Drawing) -> int:
    value = db.query(models.Project.organization_id).filter(models.Project.id == drawing.project_id).scalar()
    if value is None:
        raise ValueError("Drawing project does not exist")
    return int(value)


def _publish(job: models.ProcessingJob) -> None:
    from celery_app import run_processing_job_task

    run_processing_job_task.apply_async(args=[job.id], task_id=job.id)


def enqueue_drawing_job(
    db,
    drawing: models.Drawing,
    job_type: str,
    *,
    requested_by_id: Optional[int] = None,
    idempotency_key: Optional[str] = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> models.ProcessingJob:
    """Commit durable state before publishing; coalesce duplicate active work."""
    if job_type not in JOB_TYPES:
        raise ValueError(f"Unsupported job type: {job_type}")
    if jobs_disabled() and job_type == "analysis":
        raise RuntimeError("Background analysis is explicitly disabled")
    if not celery_configured():
        raise RuntimeError("REDIS_URL is required for durable processing jobs")

    if idempotency_key:
        existing = db.query(models.ProcessingJob).filter(
            models.ProcessingJob.organization_id == _organization_id(db, drawing),
            models.ProcessingJob.idempotency_key == idempotency_key,
        ).first()
        if existing:
            return existing

    existing = db.query(models.ProcessingJob).filter(
        models.ProcessingJob.drawing_id == drawing.id,
        models.ProcessingJob.job_type == job_type,
        models.ProcessingJob.status.in_(ACTIVE_STATUSES),
    ).order_by(models.ProcessingJob.created_at.desc()).first()
    if existing:
        return existing

    organization_id = _organization_id(db, drawing)
    job_id = uuid.uuid4().hex
    key = idempotency_key or f"{job_type}:{drawing.id}:{job_id}"
    job = models.ProcessingJob(
        id=job_id,
        organization_id=organization_id,
        project_id=drawing.project_id,
        drawing_id=drawing.id,
        requested_by_id=requested_by_id,
        job_type=job_type,
        status=models.JobStatus.QUEUED.value,
        progress=0,
        max_attempts=max(1, max_attempts),
        idempotency_key=key,
        payload_json=json.dumps({"file_path": drawing.file_path, "page_number": drawing.page_number or 0}),
        celery_task_id=job_id,
    )
    db.add(job)
    if job_type == "analysis":
        drawing.processing_status = models.ProcessingStatus.PROCESSING
        drawing.processing_job_id = job_id
        drawing.processing_error = None
    db.commit()

    try:
        _publish(job)
    except Exception as exc:
        job.status = models.JobStatus.RETRYING.value
        job.error = f"Queue publish failed: {exc}"[:2000]
        job.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=retry_delay_seconds(1))
        job.updated_at = datetime.now(timezone.utc)
        db.commit()
        raise RuntimeError("Durable job was recorded but Redis publish failed") from exc
    return job


def update_job_progress(job_id: str, progress: int, result: Optional[dict] = None) -> None:
    db = SessionLocal()
    try:
        job = db.query(models.ProcessingJob).filter(models.ProcessingJob.id == job_id).first()
        if not job or job.status not in ACTIVE_STATUSES:
            return
        job.progress = max(job.progress or 0, min(99, int(progress)))
        if result is not None:
            job.result_json = json.dumps(result)
        job.updated_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()


def _is_transient(exc: Exception) -> bool:
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return True
    try:
        import storage
        if isinstance(exc, storage.StorageOperationError):
            return True
    except Exception:
        pass
    name = type(exc).__name__.lower()
    message = str(exc).lower()
    return any(token in name or token in message for token in (
        "timeout", "connection", "temporar", "rate limit", "503", "502", "redis",
    ))


def _run_work(job: models.ProcessingJob, progress: Callable[[int], None]) -> dict:
    payload = json.loads(job.payload_json or "{}")
    if job.job_type == "analysis":
        import asyncio
        from routes.takeoff_routes import _run_ai_analysis
        work_db = SessionLocal()
        try:
            asyncio.run(_run_ai_analysis(
                job.drawing_id,
                payload["file_path"],
                work_db,
                int(payload.get("page_number", 0)),
                job_id=job.id,
                progress_callback=progress,
                raise_errors=True,
            ))
        finally:
            work_db.close()
        return {"drawing_id": job.drawing_id, "analysis": "complete"}
    if job.job_type == "tiles":
        from routes.upload_routes import _generate_tiles
        return _generate_tiles(
            job.drawing_id,
            job.organization_id,
            job.project_id,
            payload["file_path"],
            int(payload.get("page_number", 0)),
            progress_callback=progress,
            raise_errors=True,
        ) or {"drawing_id": job.drawing_id, "tiles": "unavailable"}
    raise PermanentJobError(f"Unsupported job type: {job.job_type}")


def execute_processing_job(job_id: str) -> dict:
    """Claim and execute one idempotent job; safe for late-ack redelivery."""
    db = SessionLocal()
    try:
        job = db.query(models.ProcessingJob).filter(models.ProcessingJob.id == job_id).with_for_update().first()
        if not job:
            raise PermanentJobError("Job does not exist")
        if job.status == models.JobStatus.SUCCEEDED.value:
            return json.loads(job.result_json or "{}")
        if job.status == models.JobStatus.FAILED.value:
            raise PermanentJobError(job.error or "Job has permanently failed")
        if job.status == models.JobStatus.RUNNING.value:
            age = datetime.now(timezone.utc) - job.updated_at
            if age.total_seconds() < STALE_SECONDS:
                return {"job_id": job.id, "status": "already_running"}
        if (
            job.status == models.JobStatus.RETRYING.value
            and job.next_attempt_at
            and job.next_attempt_at > datetime.now(timezone.utc)
        ):
            return {"job_id": job.id, "status": "retry_scheduled"}
        job.status = models.JobStatus.RUNNING.value
        job.attempt_count = int(job.attempt_count or 0) + 1
        job.progress = 1
        job.started_at = job.started_at or datetime.now(timezone.utc)
        job.next_attempt_at = None
        job.updated_at = datetime.now(timezone.utc)
        if job.job_type == "analysis":
            drawing = db.query(models.Drawing).filter(models.Drawing.id == job.drawing_id).first()
            if drawing:
                drawing.processing_status = models.ProcessingStatus.PROCESSING
                drawing.processing_attempts = job.attempt_count
                drawing.processing_started_at = job.started_at
        db.commit()
        # SQLAlchemy expires ORM attributes on commit. Copy the immutable work
        # envelope before closing the claiming transaction so workers never
        # rely on a detached ORM instance.
        detached_job = SimpleNamespace(
            id=job.id,
            organization_id=job.organization_id,
            project_id=job.project_id,
            drawing_id=job.drawing_id,
            job_type=job.job_type,
            payload_json=job.payload_json,
        )
    finally:
        db.close()

    progress = lambda value: update_job_progress(job_id, value)
    try:
        result = _run_work(detached_job, progress)
    except Exception as exc:
        db = SessionLocal()
        try:
            job = db.query(models.ProcessingJob).filter(models.ProcessingJob.id == job_id).first()
            transient = _is_transient(exc) and job and job.attempt_count < job.max_attempts
            if job:
                job.status = models.JobStatus.RETRYING.value if transient else models.JobStatus.FAILED.value
                job.error = str(exc)[:2000]
                job.updated_at = datetime.now(timezone.utc)
                job.next_attempt_at = (
                    job.updated_at + timedelta(seconds=retry_delay_seconds(job.attempt_count))
                    if transient else None
                )
                if not transient:
                    job.completed_at = datetime.now(timezone.utc)
                if job.job_type == "analysis":
                    drawing = db.query(models.Drawing).filter(models.Drawing.id == job.drawing_id).first()
                    if drawing:
                        drawing.processing_status = models.ProcessingStatus.PROCESSING if transient else models.ProcessingStatus.FAILED
                        drawing.processing_error = str(exc)[:2000]
                db.commit()
                attempts, maximum = job.attempt_count, job.max_attempts
            else:
                attempts, maximum = 1, 1
        finally:
            db.close()
        if transient:
            raise RetryableJobError(str(exc), attempts, maximum) from exc
        raise PermanentJobError(str(exc)) from exc

    db = SessionLocal()
    try:
        job = db.query(models.ProcessingJob).filter(models.ProcessingJob.id == job_id).first()
        if job:
            job.status = models.JobStatus.SUCCEEDED.value
            job.progress = 100
            job.error = None
            job.result_json = json.dumps(result)
            job.completed_at = datetime.now(timezone.utc)
            job.next_attempt_at = None
            job.updated_at = job.completed_at
            db.commit()
    finally:
        db.close()
    return result


def recover_stale_jobs() -> int:
    """Republish durable queued/retrying and stale-running rows after outages."""
    db = SessionLocal()
    recovered = 0
    try:
        stale_before = datetime.now(timezone.utc) - timedelta(seconds=STALE_SECONDS)
        jobs = db.query(models.ProcessingJob).filter(
            (models.ProcessingJob.status.in_([
                models.JobStatus.QUEUED.value, models.JobStatus.RETRYING.value,
            ])) | (
                (models.ProcessingJob.status == models.JobStatus.RUNNING.value)
                & (models.ProcessingJob.updated_at < stale_before)
            )
        ).all()
        for job in jobs:
            now = datetime.now(timezone.utc)
            if job.next_attempt_at and job.next_attempt_at > now:
                continue
            if job.attempt_count >= job.max_attempts:
                job.status = models.JobStatus.FAILED.value
                job.error = job.error or "Job exceeded maximum recovery attempts"
                job.completed_at = datetime.now(timezone.utc)
                job.next_attempt_at = None
                if job.job_type == "analysis":
                    drawing = db.query(models.Drawing).filter(models.Drawing.id == job.drawing_id).first()
                    if drawing:
                        drawing.processing_status = models.ProcessingStatus.FAILED
                        drawing.processing_error = job.error
                continue
            job.status = models.JobStatus.RETRYING.value
            job.next_attempt_at = None
            job.updated_at = datetime.now(timezone.utc)
            db.commit()
            try:
                _publish(job)
                recovered += 1
            except Exception as exc:
                job.error = f"Recovery publish failed: {exc}"[:2000]
                db.commit()
        db.commit()
    finally:
        db.close()
    return recovered
