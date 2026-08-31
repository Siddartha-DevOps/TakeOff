from types import SimpleNamespace

import analysis_jobs
import job_system


def test_queue_backend_requires_explicit_redis(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    assert job_system.queue_backend() == "unavailable"
    monkeypatch.setenv("REDIS_URL", "redis://queue.internal:6379/0")
    assert job_system.queue_backend() == "celery"


def test_analysis_facade_returns_persisted_job_metadata(monkeypatch):
    recorded = []
    job = SimpleNamespace(id="job-1", status="queued", progress=0)
    monkeypatch.setattr(job_system, "enqueue_drawing_job", lambda *args, **kwargs: recorded.append((args, kwargs)) or job)
    result = analysis_jobs.enqueue_analysis(object(), SimpleNamespace(id=7), requested_by_id=9)
    assert result == {"backend": "celery", "job_id": "job-1", "status": "queued", "progress": 0}
    assert recorded[0][0][2] == "analysis"
    assert recorded[0][1]["requested_by_id"] == 9


def test_tile_facade_uses_same_durable_queue(monkeypatch):
    recorded = []
    job = SimpleNamespace(id="job-2", status="queued", progress=0)
    monkeypatch.setattr(job_system, "enqueue_drawing_job", lambda *args, **kwargs: recorded.append((args, kwargs)) or job)
    result = analysis_jobs.enqueue_tiles(object(), SimpleNamespace(id=8))
    assert result["job_id"] == "job-2"
    assert recorded[0][0][2] == "tiles"


def test_retry_classifier_distinguishes_transient_and_permanent_errors():
    assert job_system._is_transient(TimeoutError("HF timeout")) is True
    assert job_system._is_transient(ValueError("invalid drawing")) is False


def test_explicit_test_isolation_disables_only_analysis_enqueue(monkeypatch):
    monkeypatch.setenv("TAKEOFF_DISABLE_BACKGROUND_ANALYSIS", "true")
    result = analysis_jobs.enqueue_analysis(object(), SimpleNamespace(id=7))
    assert result == {"backend": "disabled", "job_id": None, "status": "disabled", "progress": 0}
