"""
Model promotion invariant (Phase 4).

Enforces "at most one ACTIVE version per model line": when a newly-evaluated model
passes the golden gate it becomes ACTIVE and any previously-ACTIVE sibling is
demoted to CANDIDATE; when it fails the gate it is registered CANDIDATE and
nothing else changes. This is the guard that keeps serving deterministic —
``ai.inference`` should only ever load the single ACTIVE weights.

``plan_promotion`` is pure (decides stages from a list of existing versions) and
unit-tested; ``apply_promotion`` applies that plan to the ``models.ModelVersion``
table (lazy DB import). Registration itself lives in
``ml/training/retrain.register_model_version`` — this adds the demotion invariant.
"""

from __future__ import annotations

from typing import Optional

ACTIVE = "ACTIVE"
CANDIDATE = "CANDIDATE"


def plan_promotion(existing: list, new_version: str, passed: bool) -> dict:
    """Decide the new version's stage and which siblings to demote.

    ``existing``: list of ``{"version_string", "stage"}`` for the same model name
    (excluding or including the new one — the new one is never self-demoted).
    Returns ``{"new_stage", "demote": [version_string, ...], "promoted": bool}``.
    """
    if not passed:
        return {"new_stage": CANDIDATE, "demote": [], "promoted": False}
    demote = [
        e["version_string"] for e in existing
        if e.get("stage") == ACTIVE and e.get("version_string") != new_version
    ]
    return {"new_stage": ACTIVE, "demote": demote, "promoted": True}


def apply_promotion(db, *, name: str, new_version: str, passed: bool) -> dict:
    """Apply the promotion plan to ModelVersion rows for ``name``. Returns the plan.

    Demotes prior ACTIVE siblings and sets the new version's stage. Field-tolerant
    (only touches attributes that exist), matching retrain.register_model_version.
    """
    import models

    rows = (
        db.query(models.ModelVersion)
        .filter(models.ModelVersion.name == name)
        .all()
    )
    existing = [{"version_string": r.version_string, "stage": getattr(
        getattr(r, "stage", None), "name", None)} for r in rows]
    plan = plan_promotion(existing, new_version, passed)

    if not hasattr(models, "ModelVersionStage"):
        return plan
    demote_set = set(plan["demote"])
    for r in rows:
        if r.version_string in demote_set:
            r.stage = models.ModelVersionStage.CANDIDATE
        if r.version_string == new_version:
            r.stage = (models.ModelVersionStage.ACTIVE if plan["promoted"]
                       else models.ModelVersionStage.CANDIDATE)
    db.commit()
    return plan
