import importlib
import sys
from enum import Enum
from types import SimpleNamespace


class _ProcessingStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


_models = SimpleNamespace(ProcessingStatus=_ProcessingStatus, Drawing=object)
_prior_models = sys.modules.get("models")
_prior_database = sys.modules.get("database")
sys.modules["models"] = _models
sys.modules["database"] = SimpleNamespace(SessionLocal=lambda: None)
analysis_jobs = importlib.import_module("analysis_jobs")
if _prior_models is None:
    del sys.modules["models"]
else:
    sys.modules["models"] = _prior_models
if _prior_database is None:
    del sys.modules["database"]
else:
    sys.modules["database"] = _prior_database


class _FakeDb:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1


def test_record_enqueue_persists_recoverable_metadata():
    db = _FakeDb()
    drawing = SimpleNamespace(
        processing_status=_ProcessingStatus.PENDING,
        processing_job_id=None,
        processing_started_at=None,
        processing_attempts=None,
        processing_error="old failure",
    )

    analysis_jobs._record_enqueue(db, drawing, "db-test-job")

    assert drawing.processing_status == _ProcessingStatus.PROCESSING
    assert drawing.processing_job_id == "db-test-job"
    assert drawing.processing_started_at is not None
    assert drawing.processing_attempts == 1
    assert drawing.processing_error is None
    assert db.commits == 1


def test_queue_backend_reports_unavailable_without_worker_or_redis(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setattr(analysis_jobs, "_queue", None)
    monkeypatch.setattr(analysis_jobs, "_worker", None)
    assert analysis_jobs.queue_backend() == "unavailable"


def test_queue_backend_prefers_celery_when_redis_is_configured(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://example.invalid:6379/0")
    assert analysis_jobs.queue_backend() == "celery"


def test_celery_job_state_is_committed_before_publish(monkeypatch):
    events = []

    class Db(_FakeDb):
        def commit(self):
            super().commit()
            events.append("commit")

    task = SimpleNamespace(
        apply_async=lambda **kwargs: events.append(("publish", kwargs))
    )
    monkeypatch.setenv("REDIS_URL", "redis://example.invalid:6379/0")
    monkeypatch.setitem(sys.modules, "celery_app", SimpleNamespace(run_ai_analysis_task=task))
    drawing = SimpleNamespace(
        id=42,
        file_path="s3://bucket/plan.pdf",
        page_number=3,
        processing_status=_ProcessingStatus.PENDING,
        processing_job_id=None,
        processing_started_at=None,
        processing_attempts=0,
        processing_error=None,
    )

    result = analysis_jobs.enqueue_analysis(Db(), drawing)

    assert events[0] == "commit"
    assert events[1][0] == "publish"
    assert events[1][1]["task_id"] == result["job_id"]
    assert events[1][1]["args"] == [42, "s3://bucket/plan.pdf", 3]
