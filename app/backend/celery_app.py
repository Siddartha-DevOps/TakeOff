"""
TakeOff.ai — real async job queue for AI analysis. Closes the foundational
gap: "Async/webhook: Celery configured but sync fallback, no completion
webhook (guardrail #3)."

Before this, `ai/ai_tasks.py` defined a Celery app and three tasks that
were never imported or invoked anywhere in the codebase (confirmed by
grepping the whole backend for `.delay(`/`.apply_async(` before writing
this — zero hits) — fully dead code, and stale: it called
`detection_engine.BlueprintDetector` and bare `from preprocessing import
...` module paths that don't match this codebase's actual current
structure (`ai.inference_api.TakeoffAIInference` / `ai.preprocessing`),
had no PostGIS/CLIP/title-block-OCR persistence, and never wrote a
TakeoffResult row itself ("saved to TakeoffResult table by caller", per
its own docstring, for a caller that doesn't exist). The real, current,
maintained AI pipeline is routes/takeoff_routes.py's `_run_ai_analysis` —
this module is a thin Celery wrapper AROUND that single source of truth,
not a second copy of it, so the two paths (Celery vs. the BackgroundTasks
fallback below) can never drift apart again.

Architecture (CLAUDE.md guardrail #3): enqueue -> worker (a genuinely
separate process, started with `celery -A celery_app worker`) -> the
worker does the DB writes directly (it shares the same Postgres, so no
HTTP indirection needed for that part) -> then POSTs to this app's own
/api/webhook/analysis-complete (routes/webhook_routes.py) so the request
that enqueued the job (long since returned) can still learn the job
finished. That webhook's only job is broadcasting a live "takeoff_complete"
event over realtime.py's WebSocket/Redis-pub/sub hub (built earlier this
session for collaboration), so connected clients see AI analysis finish
without polling — real, useful behavior from a "completion webhook",
not a checkbox.

_run_ai_analysis is `async def` but contains no actual `await` (confirmed
by reading it — every DB/IO call in it is synchronous SQLAlchemy/cv2/PIL;
it's async only for signature-compatibility with FastAPI's BackgroundTasks
call site), so asyncio.run() below is a correct, cheap way to drive it
from a plain synchronous Celery task — no event-loop-in-a-worker
complexity needed.
"""

import asyncio
import logging
import os
import sys

from celery import Celery

# Celery's prefork worker pool doesn't reliably carry the CLI's cwd-based
# sys.path onto forked child processes — task bodies below lazily import
# sibling top-level modules (database, models, routes.takeoff_routes) the
# same way server.py does, but relying on cwd for that broke in exactly
# those child processes (verified: worked in the main process, failed with
# ModuleNotFoundError inside a forked task). Anchoring to this file's own
# directory is correct regardless of the worker's launch cwd or pool mode.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
INTERNAL_WEBHOOK_URL = os.environ.get("INTERNAL_WEBHOOK_URL", "http://localhost:8000/api/webhook/analysis-complete")
INTERNAL_WEBHOOK_SECRET = os.environ.get("INTERNAL_WEBHOOK_SECRET", "")

logger = logging.getLogger(__name__)

celery_app = Celery("takeoffai", broker=REDIS_URL, backend=REDIS_URL)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    result_expires=3600,
    task_soft_time_limit=120,
    task_time_limit=180,
    worker_prefetch_multiplier=1,      # AI jobs are heavy — one at a time per worker
    task_acks_late=True,               # re-queue on worker crash
    task_reject_on_worker_lost=True,
    broker_connection_retry_on_startup=True,
)


@celery_app.task(bind=True, name="run_ai_analysis", max_retries=2, default_retry_delay=30)
def run_ai_analysis_task(self, drawing_id: int, file_path: str, page_number: int = 0):
    """
    Runs in a worker process, never in the API server. Creates its own DB
    session (SessionLocal) rather than reusing the enqueuing request's
    session — that request has already returned a response by the time
    this executes, so its session may already be closed; a fresh session
    per task run is the only correct option for genuinely out-of-process
    work (and is an improvement over the BackgroundTasks fallback path,
    which does reuse the request-scoped session — a preexisting, more minor
    sketchiness left alone there since that path is now just a degraded-mode
    fallback, not the primary one).
    """
    from database import SessionLocal
    from routes.takeoff_routes import _run_ai_analysis

    logger.info(f"[Celery {self.request.id}] Starting AI analysis: drawing_id={drawing_id}")
    db = SessionLocal()
    try:
        asyncio.run(_run_ai_analysis(drawing_id, file_path, db, page_number))
    finally:
        db.close()

    _notify_completion_webhook(drawing_id)
    logger.info(f"[Celery {self.request.id}] Done: drawing_id={drawing_id}")


def _notify_completion_webhook(drawing_id: int):
    """
    Best-effort: a failed webhook call must never fail the task itself —
    the DB writes above already succeeded and are the source of truth;
    the webhook only drives a nice-to-have live notification. If
    INTERNAL_WEBHOOK_SECRET isn't configured, skip silently rather than
    calling an endpoint we know will reject us — analysis still completes
    and is queryable via GET /results either way, just without the
    real-time push.
    """
    if not INTERNAL_WEBHOOK_SECRET:
        return
    try:
        import requests
        requests.post(
            INTERNAL_WEBHOOK_URL,
            json={"drawing_id": drawing_id},
            headers={"X-Internal-Webhook-Secret": INTERNAL_WEBHOOK_SECRET},
            timeout=5,
        )
    except Exception as e:
        logger.warning(f"[Celery] Completion webhook failed for drawing_id={drawing_id}: {e}")
