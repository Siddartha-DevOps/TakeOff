"""
TakeOff.ai — Eval harness API: register/evaluate/promote ModelVersions.

Closes memory/TOGAL_PARITY_REAUDIT.md #14/§5: "ModelVersion table exists
but nothing gates promotion" (CLAUDE.md §5 names the entity, never specs
it — see models.ModelVersion's docstring). eval_harness.py does the actual
metric computation; this module is the thin CRUD/gating API around it.
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

import models
import schemas
from auth import get_current_user
from database import get_db
from eval_harness import evaluate_model_version, gate_promotion

router = APIRouter(prefix="/eval", tags=["Eval Harness"])


@router.post("/model-versions", response_model=schemas.ModelVersion)
async def create_model_version(
    payload: schemas.ModelVersionCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    existing = db.query(models.ModelVersion).filter(
        models.ModelVersion.version_string == payload.version_string
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="version_string already registered")

    mv = models.ModelVersion(name=payload.name, version_string=payload.version_string, notes=payload.notes)
    db.add(mv)
    db.commit()
    db.refresh(mv)
    return mv


@router.get("/model-versions", response_model=list[schemas.ModelVersion])
async def list_model_versions(
    name: Optional[str] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(models.ModelVersion)
    if name:
        query = query.filter(models.ModelVersion.name == name)
    return query.order_by(models.ModelVersion.created_at.desc()).all()


@router.get("/model-versions/{model_version_id}", response_model=schemas.ModelVersion)
async def get_model_version(
    model_version_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    mv = db.query(models.ModelVersion).filter(models.ModelVersion.id == model_version_id).first()
    if not mv:
        raise HTTPException(status_code=404, detail="ModelVersion not found")
    return mv


class EvaluateRequest(BaseModel):
    project_id: Optional[int] = None
    thresholds: Optional[dict] = None


def _get_model_version(model_version_id: int, db: Session) -> models.ModelVersion:
    mv = db.query(models.ModelVersion).filter(models.ModelVersion.id == model_version_id).first()
    if not mv:
        raise HTTPException(status_code=404, detail="ModelVersion not found")
    return mv


def _record_eval(mv: models.ModelVersion, metrics: dict) -> None:
    mv.miou = metrics["miou"]
    mv.map_score = metrics["map_proxy"]
    mv.measurement_error_pct = metrics["measurement_error_pct"]
    mv.eval_sample_size = (
        metrics["miou_sample_size"] + metrics["map_proxy_sample_size"] + metrics["measurement_error_sample_size"]
    )
    mv.evaluated_at = datetime.now(timezone.utc)


@router.post("/model-versions/{model_version_id}/evaluate")
async def evaluate(
    model_version_id: int,
    payload: EvaluateRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Runs the harness and stores the result as an audit record on the
    ModelVersion row — does NOT change stage. Only /promote actually gates;
    this is for checking where a candidate stands before attempting it.
    """
    mv = _get_model_version(model_version_id, db)
    metrics = evaluate_model_version(db, mv.version_string, project_id=payload.project_id)
    passed, reasons = gate_promotion(metrics, thresholds=payload.thresholds)

    _record_eval(mv, metrics)
    db.commit()
    db.refresh(mv)

    return {"model_version": mv, "metrics": metrics, "gate_passed": passed, "gate_reasons": reasons}


@router.post("/model-versions/{model_version_id}/promote")
async def promote(
    model_version_id: int,
    payload: EvaluateRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Re-runs the harness fresh (never trusts a possibly-stale stored eval)
    and only flips stage to ACTIVE if it passes. On pass, demotes whatever
    was previously ACTIVE for this model `name` to ARCHIVED — at most one
    ACTIVE version per model line at a time. On fail, stage becomes
    REJECTED and the response is a 422 carrying the metrics + reasons, so
    a caller can't mistake "failed the gate" for a transient error.
    """
    mv = _get_model_version(model_version_id, db)
    metrics = evaluate_model_version(db, mv.version_string, project_id=payload.project_id)
    passed, reasons = gate_promotion(metrics, thresholds=payload.thresholds)

    _record_eval(mv, metrics)

    if not passed:
        mv.stage = models.ModelVersionStage.REJECTED
        db.commit()
        raise HTTPException(
            status_code=422,
            detail={"message": "Model version failed the promotion gate", "reasons": reasons, "metrics": metrics},
        )

    db.query(models.ModelVersion).filter(
        models.ModelVersion.name == mv.name,
        models.ModelVersion.stage == models.ModelVersionStage.ACTIVE,
    ).update({"stage": models.ModelVersionStage.ARCHIVED})

    mv.stage = models.ModelVersionStage.ACTIVE
    mv.promoted_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(mv)

    return {"model_version": mv, "metrics": metrics, "gate_passed": True}
