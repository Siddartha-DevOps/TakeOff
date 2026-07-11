import os

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

import models
import realtime
from database import SessionLocal

router = APIRouter(prefix="/webhook", tags=["Webhooks"])

# Internal job-completion webhook — closes the foundational "Celery
# configured but sync fallback, no completion webhook (guardrail #3)" gap.
# Not a third-party webhook like routes/stripe_routes.py's (verified via
# Stripe's signature scheme) — this one is called by OUR OWN Celery worker
# (celery_app.py) after it finishes AI analysis, so it's secured with a
# shared secret instead. Its only job is broadcasting a live notification
# over realtime.py's existing WebSocket/Redis hub; the actual DB write
# already happened in the worker before this fires.

INTERNAL_WEBHOOK_SECRET = os.environ.get("INTERNAL_WEBHOOK_SECRET", "")


class AnalysisCompletePayload(BaseModel):
    drawing_id: int


@router.post("/analysis-complete")
async def analysis_complete_webhook(
    payload: AnalysisCompletePayload,
    x_internal_webhook_secret: str = Header(default=""),
):
    if not INTERNAL_WEBHOOK_SECRET or x_internal_webhook_secret != INTERNAL_WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Invalid or missing webhook secret")

    # A plain SessionLocal(), not Depends(get_db): this endpoint is called
    # by our own worker process, not an authenticated browser session, so
    # there's no current_user/request-scoped session to inject.
    db: Session = SessionLocal()
    try:
        drawing = db.query(models.Drawing).filter(models.Drawing.id == payload.drawing_id).first()
        if not drawing:
            raise HTTPException(status_code=404, detail="Drawing not found")

        await realtime.hub.publish(drawing.project_id, {
            "type": "takeoff_complete",
            "drawing_id": drawing.id,
            "status": drawing.processing_status.value,
        })
    finally:
        db.close()

    return {"received": True}
