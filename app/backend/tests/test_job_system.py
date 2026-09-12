import asyncio
import json
import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import job_system
import models
from routes import job_routes


class Query:
    def __init__(self, db, model):
        self.db, self.model = db, model

    def filter(self, *args): return self
    def order_by(self, *args): return self
    def limit(self, *args): return self
    def with_for_update(self): return self
    def first(self): return self.db.values.get(self.model)
    def scalar(self): return self.db.scalars.get(self.model)
    def all(self): return self.db.all_values.get(self.model, [])


class Db:
    def __init__(self, job=None, drawing=None, organization_id=3):
        self.values = {models.ProcessingJob: job, models.Drawing: drawing}
        self.scalars = {models.Project.organization_id: organization_id}
        self.all_values = {}
        self.added, self.commits = [], 0

    def query(self, model): return Query(self, model)
    def add(self, value):
        self.added.append(value)
        if isinstance(value, models.ProcessingJob): self.values[models.ProcessingJob] = value
    def commit(self): self.commits += 1
    def close(self): pass


def drawing():
    return SimpleNamespace(
        id=7, project_id=5, file_path="s3://takeoff/organizations/3/projects/5/plan.pdf",
        page_number=2, processing_status=models.ProcessingStatus.PENDING,
        processing_job_id=None, processing_error=None, processing_attempts=0,
        processing_started_at=None,
    )


def job(status="queued", attempts=0, maximum=3):
    now = models.datetime.now(models.timezone.utc)
    return models.ProcessingJob(
        id="job-1", organization_id=3, project_id=5, drawing_id=7,
        job_type="analysis", status=status, progress=0, attempt_count=attempts,
        max_attempts=maximum, idempotency_key="analysis:7:test",
        payload_json=json.dumps({"file_path": "s3://takeoff/plan.pdf", "page_number": 2}),
        created_at=now, updated_at=now,
        next_attempt_at=None,
    )


def test_enqueue_persists_before_publish_and_coalesces_duplicate(monkeypatch):
    db, source = Db(drawing=drawing()), drawing()
    events = []
    monkeypatch.setenv("REDIS_URL", "redis://queue:6379/0")
    monkeypatch.setattr(job_system, "_publish", lambda queued: events.append((queued.id, db.commits)))
    queued = job_system.enqueue_drawing_job(db, source, "analysis", idempotency_key="upload:a:analysis:2")
    assert queued.status == "queued"
    assert events == [(queued.id, 1)]
    assert source.processing_job_id == queued.id
    duplicate = job_system.enqueue_drawing_job(db, source, "analysis")
    assert duplicate.id == queued.id
    assert len(events) == 1


def test_success_and_duplicate_execution_are_idempotent(monkeypatch):
    queued, source = job(), drawing()
    db = Db(queued, source)
    monkeypatch.setattr(job_system, "SessionLocal", lambda: db)
    calls = []
    monkeypatch.setattr(job_system, "_run_work", lambda value, progress: calls.append(value.id) or {"ok": True})
    assert job_system.execute_processing_job(queued.id) == {"ok": True}
    assert queued.status == "succeeded" and queued.progress == 100
    assert job_system.execute_processing_job(queued.id) == {"ok": True}
    assert calls == [queued.id]


def test_concurrent_redelivery_does_not_run_active_work_twice(monkeypatch):
    active, source = job(status="running", attempts=1), drawing()
    db = Db(active, source)
    monkeypatch.setattr(job_system, "SessionLocal", lambda: db)
    monkeypatch.setattr(job_system, "_run_work", lambda *args: pytest.fail("active work ran twice"))
    assert job_system.execute_processing_job(active.id) == {
        "job_id": active.id,
        "status": "already_running",
    }


def test_transient_failure_retries_then_max_retry_fails(monkeypatch):
    queued, source = job(), drawing()
    db = Db(queued, source)
    monkeypatch.setattr(job_system, "SessionLocal", lambda: db)
    monkeypatch.setattr(job_system, "_run_work", lambda *args: (_ for _ in ()).throw(TimeoutError("HF timeout")))
    with pytest.raises(job_system.RetryableJobError):
        job_system.execute_processing_job(queued.id)
    assert queued.status == "retrying" and queued.attempt_count == 1
    assert queued.next_attempt_at is not None
    queued.attempt_count = 2
    queued.status = "retrying"
    queued.next_attempt_at = None
    with pytest.raises(job_system.PermanentJobError):
        job_system.execute_processing_job(queued.id)
    assert queued.status == "failed" and queued.attempt_count == 3


def test_crash_recovery_republishes_stale_running_job(monkeypatch):
    stale = job(status="running", attempts=1)
    stale.updated_at = models.datetime.now(models.timezone.utc) - job_system.timedelta(seconds=job_system.STALE_SECONDS + 1)
    db = Db(stale, drawing())
    db.all_values[models.ProcessingJob] = [stale]
    monkeypatch.setattr(job_system, "SessionLocal", lambda: db)
    published = []
    monkeypatch.setattr(job_system, "_publish", lambda value: published.append(value.id))
    assert job_system.recover_stale_jobs() == 1
    assert stale.status == "retrying" and published == [stale.id]


def test_recovery_respects_persisted_retry_backoff(monkeypatch):
    waiting = job(status="retrying", attempts=1)
    waiting.next_attempt_at = models.datetime.now(models.timezone.utc) + job_system.timedelta(minutes=2)
    db = Db(waiting, drawing())
    db.all_values[models.ProcessingJob] = [waiting]
    monkeypatch.setattr(job_system, "SessionLocal", lambda: db)
    monkeypatch.setattr(job_system, "_publish", lambda value: pytest.fail("retry backoff was bypassed"))
    assert job_system.recover_stale_jobs() == 0


def test_exhausted_recovery_marks_job_and_drawing_failed(monkeypatch):
    exhausted, source = job(status="running", attempts=3, maximum=3), drawing()
    exhausted.updated_at = models.datetime.now(models.timezone.utc) - job_system.timedelta(
        seconds=job_system.STALE_SECONDS + 1
    )
    db = Db(exhausted, source)
    db.all_values[models.ProcessingJob] = [exhausted]
    monkeypatch.setattr(job_system, "SessionLocal", lambda: db)
    monkeypatch.setattr(job_system, "_publish", lambda value: pytest.fail("exhausted job was republished"))
    assert job_system.recover_stale_jobs() == 0
    assert exhausted.status == "failed"
    assert exhausted.completed_at is not None
    assert source.processing_status == models.ProcessingStatus.FAILED


def test_s3_reference_reaches_analysis_worker(monkeypatch):
    queued = job()
    seen = {}

    async def fake_analysis(drawing_id, file_path, db, page_number, **kwargs):
        seen.update(drawing_id=drawing_id, file_path=file_path, page_number=page_number, job_id=kwargs["job_id"])

    import routes.takeoff_routes as takeoff_routes
    monkeypatch.setattr(takeoff_routes, "_run_ai_analysis", fake_analysis)
    monkeypatch.setattr(job_system, "SessionLocal", lambda: Db())
    assert job_system._run_work(queued, lambda value: None)["analysis"] == "complete"
    assert seen == {"drawing_id": 7, "file_path": "s3://takeoff/plan.pdf", "page_number": 2, "job_id": "job-1"}


def test_durable_tile_job_uses_s3_source_and_is_idempotent(monkeypatch):
    queued = job()
    queued.job_type = "tiles"
    seen = []

    def fake_tiles(*args, **kwargs):
        seen.append((args, kwargs))
        return {"max_level": 4}

    import routes.upload_routes as upload_routes
    monkeypatch.setattr(upload_routes, "_generate_tiles", fake_tiles)
    first = job_system._run_work(queued, lambda value: None)
    second = job_system._run_work(queued, lambda value: None)
    assert first == second == {"max_level": 4}
    assert len(seen) == 2
    assert all(call[0][3] == "s3://takeoff/plan.pdf" for call in seen)
    assert all(call[1]["raise_errors"] is True for call in seen)


def test_job_status_is_tenant_safe():
    current_user = SimpleNamespace(organization_id=99)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(job_routes.get_job("foreign-job", current_user=current_user, db=Db(job=None)))
    assert exc.value.status_code == 404


def test_public_job_status_reports_progress_attempts_and_error():
    value = job(status="retrying", attempts=2)
    value.progress = 55
    value.error = "temporary storage outage"
    public = job_routes._public(value)
    assert public["status"] == "retrying"
    assert public["progress"] == 55
    assert public["attempt_count"] == 2
    assert public["error"] == "temporary storage outage"


def test_worker_readiness_requires_a_live_worker(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://queue:6379/0")
    monkeypatch.setattr(job_system, "redis_ready", lambda: True)

    class Inspector:
        def ping(self): return {"celery@worker": {"ok": "pong"}}

    control = SimpleNamespace(inspect=lambda timeout: Inspector())
    monkeypatch.setitem(sys.modules, "celery_app", SimpleNamespace(celery_app=SimpleNamespace(control=control)))
    assert job_system.celery_worker_ready() is True
