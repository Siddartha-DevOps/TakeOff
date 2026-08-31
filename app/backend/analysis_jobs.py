"""Compatibility facade over the durable PostgreSQL/Celery job system."""

from job_system import (
    celery_configured,
    celery_worker_ready,
    jobs_disabled as analysis_disabled,
    queue_backend,
    redis_ready,
)


def enqueue_analysis(db, drawing, requested_by_id=None, idempotency_key=None):
    if analysis_disabled():
        return {"backend": "disabled", "job_id": None, "status": "disabled", "progress": 0}
    from job_system import enqueue_drawing_job
    job = enqueue_drawing_job(db, drawing, "analysis", requested_by_id=requested_by_id, idempotency_key=idempotency_key)
    return {"backend": "celery", "job_id": job.id, "status": job.status, "progress": job.progress}


def enqueue_tiles(db, drawing, requested_by_id=None, idempotency_key=None):
    from job_system import enqueue_drawing_job
    job = enqueue_drawing_job(db, drawing, "tiles", requested_by_id=requested_by_id, idempotency_key=idempotency_key)
    return {"backend": "celery", "job_id": job.id, "status": job.status, "progress": job.progress}


async def start_analysis_runner() -> int:
    return 0


async def stop_analysis_runner() -> None:
    return None
