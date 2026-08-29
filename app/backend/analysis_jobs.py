"""Durable orchestration for drawing-analysis jobs.

Celery/Redis remains the preferred multi-process queue.  Deployments without
Redis use a single in-process worker backed by the Drawing row itself: job
state is committed before enqueueing and unfinished rows are recovered after
a process restart.  That is materially safer than FastAPI BackgroundTasks,
which previously held a request-scoped SQLAlchemy session after the response
had closed and silently lost work on every restart.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone

import models
from database import SessionLocal

logger = logging.getLogger(__name__)

_queue: asyncio.Queue[int] | None = None
_worker: asyncio.Task | None = None
_queued: set[int] = set()


def analysis_disabled() -> bool:
    """Disable only automatic raster inference for deterministic E2E runs."""
    return os.environ.get("TAKEOFF_DISABLE_BACKGROUND_ANALYSIS", "").lower() in {
        "1", "true", "yes", "on",
    }


def celery_configured() -> bool:
    return bool(os.environ.get("REDIS_URL"))


def local_runner_ready() -> bool:
    return _queue is not None and _worker is not None and not _worker.done()


def queue_backend() -> str:
    if celery_configured():
        return "celery"
    if local_runner_ready():
        return "database_recovery"
    return "unavailable"


def _record_enqueue(db, drawing: models.Drawing, job_id: str) -> None:
    drawing.processing_status = models.ProcessingStatus.PROCESSING
    drawing.processing_job_id = job_id
    drawing.processing_started_at = datetime.now(timezone.utc)
    drawing.processing_attempts = int(drawing.processing_attempts or 0) + 1
    drawing.processing_error = None
    db.commit()


def enqueue_analysis(db, drawing: models.Drawing) -> dict:
    """Persist and enqueue one analysis job, returning public job metadata."""
    if analysis_disabled():
        return {"backend": "disabled", "job_id": None}
    if celery_configured():
        from celery_app import run_ai_analysis_task

        # Persist first so an immediately scheduled worker can never finish and
        # then be overwritten back to PROCESSING by the API process.
        job_id = uuid.uuid4().hex
        _record_enqueue(db, drawing, job_id)
        run_ai_analysis_task.apply_async(
            args=[drawing.id, drawing.file_path, drawing.page_number or 0],
            task_id=job_id,
        )
        return {"backend": "celery", "job_id": job_id}

    if not local_runner_ready():
        raise RuntimeError("The database-backed analysis worker is not running")
    job_id = f"db-{uuid.uuid4().hex}"
    _record_enqueue(db, drawing, job_id)
    if drawing.id not in _queued:
        _queued.add(drawing.id)
        _queue.put_nowait(drawing.id)
    return {"backend": "database_recovery", "job_id": job_id}


def _run_one(drawing_id: int) -> None:
    """Run one job with a fresh session; safe after the HTTP request ends."""
    from routes.takeoff_routes import _run_ai_analysis

    db = SessionLocal()
    try:
        drawing = db.query(models.Drawing).filter(models.Drawing.id == drawing_id).first()
        if not drawing:
            return
        asyncio.run(_run_ai_analysis(
            drawing.id, drawing.file_path, db, drawing.page_number or 0
        ))
        db.expire_all()
        drawing = db.query(models.Drawing).filter(models.Drawing.id == drawing_id).first()
        if drawing and drawing.processing_status == models.ProcessingStatus.PROCESSING:
            drawing.processing_status = models.ProcessingStatus.FAILED
            drawing.processing_error = "Analysis worker exited without a terminal status"
            db.commit()
    except Exception as exc:  # final safety net around the route pipeline
        db.rollback()
        drawing = db.query(models.Drawing).filter(models.Drawing.id == drawing_id).first()
        if drawing:
            drawing.processing_status = models.ProcessingStatus.FAILED
            drawing.processing_error = str(exc)[:2000]
            db.commit()
        logger.exception("analysis job failed: drawing_id=%s", drawing_id)
    finally:
        db.close()


async def _worker_loop() -> None:
    assert _queue is not None
    while True:
        drawing_id = await _queue.get()
        try:
            await asyncio.to_thread(_run_one, drawing_id)
        finally:
            _queued.discard(drawing_id)
            _queue.task_done()


async def start_analysis_runner() -> int:
    """Start the fallback worker and recover unfinished database jobs."""
    global _queue, _worker
    if analysis_disabled():
        logger.info("background raster analysis disabled by TAKEOFF_DISABLE_BACKGROUND_ANALYSIS")
        return 0
    if celery_configured() or local_runner_ready():
        return 0
    _queue = asyncio.Queue()
    _worker = asyncio.create_task(_worker_loop(), name="takeoff-analysis-worker")

    db = SessionLocal()
    try:
        pending = db.query(models.Drawing.id).filter(
            models.Drawing.processing_status.in_([
                models.ProcessingStatus.PENDING,
                models.ProcessingStatus.PROCESSING,
            ])
        ).all()
    finally:
        db.close()
    for (drawing_id,) in pending:
        if drawing_id not in _queued:
            _queued.add(drawing_id)
            _queue.put_nowait(drawing_id)
    if pending:
        logger.warning("recovered %s unfinished analysis jobs", len(pending))
    return len(pending)


async def stop_analysis_runner() -> None:
    global _queue, _worker
    if _worker is not None:
        _worker.cancel()
        try:
            await _worker
        except asyncio.CancelledError:
            pass
    _queue = None
    _worker = None
    _queued.clear()
