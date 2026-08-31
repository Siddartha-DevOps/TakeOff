"""Celery entry point for durable PostgreSQL-tracked processing jobs."""

import os
import sys
from celery import Celery

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
REDIS_URL = os.environ.get("REDIS_URL")
# Development imports may use an in-memory transport, but job_system refuses
# to enqueue without REDIS_URL. Production therefore has no silent fallback.
BROKER_URL = REDIS_URL or "memory://"
RESULT_BACKEND = REDIS_URL or "cache+memory://"

celery_app = Celery("takeoffai", broker=BROKER_URL, backend=RESULT_BACKEND)
celery_app.conf.update(
    task_serializer="json", result_serializer="json", accept_content=["json"], result_expires=3600,
    task_soft_time_limit=int(os.environ.get("JOB_SOFT_TIME_LIMIT", "900")),
    task_time_limit=int(os.environ.get("JOB_HARD_TIME_LIMIT", "1200")),
    worker_prefetch_multiplier=1, task_acks_late=True, task_reject_on_worker_lost=True,
    broker_connection_retry_on_startup=True, broker_connection_timeout=3,
    broker_transport_options={"socket_connect_timeout": 3, "socket_timeout": 5, "visibility_timeout": 3600},
    beat_schedule={"recover-durable-processing-jobs": {"task": "recover_processing_jobs", "schedule": 60.0}},
)


@celery_app.task(bind=True, name="run_processing_job", max_retries=10)
def run_processing_job_task(self, job_id: str):
    from job_system import PermanentJobError, RetryableJobError, execute_processing_job, retry_delay_seconds
    try:
        return execute_processing_job(job_id)
    except RetryableJobError as exc:
        if exc.attempt_count >= exc.max_attempts:
            raise PermanentJobError(str(exc)) from exc
        countdown = retry_delay_seconds(exc.attempt_count)
        raise self.retry(exc=exc, countdown=countdown, max_retries=exc.max_attempts - 1)


@celery_app.task(name="recover_processing_jobs")
def recover_processing_jobs_task():
    from job_system import recover_stale_jobs
    return {"recovered": recover_stale_jobs()}
