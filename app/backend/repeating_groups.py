"""
TakeOff.ai — Repeating Groups: measure one master unit, apply it N times.
Closes memory/TOGAL_PARITY_REAUDIT.md #19's first half: "take off one
master unit (hotel room/apartment) -> apply to hundreds of identical
spaces."

A MasterUnit ties one Drawing (a sheet the estimator measured once — the
representative hotel room, apartment layout, etc.) to an instance_count.
apply_multiplier() scales that drawing's quantities by instance_count and
is called right after export_engine.extract_rows() at both of its real
call sites (routes/export_routes.py, handoff_engine.py) — every consumer
of project-wide quantities (rich export, the estimating handoff) picks up
repeating groups automatically without each needing its own multiplier
logic. extract_rows() itself is untouched: it stays "raw truth for one
drawing", and the multiplier is a separate, composable step, matching how
export_engine.apply_multiplier() (the export feature's *global*
per-request multiplier) already works — this is the same idea, scoped to
one drawing and persisted instead of typed in at export time.
"""

from typing import Optional

import models


def get_master_unit(db, drawing_id: int) -> Optional["models.MasterUnit"]:
    return db.query(models.MasterUnit).filter(models.MasterUnit.drawing_id == drawing_id).first()


def apply_multiplier(db, drawing: "models.Drawing", rows: list[dict]) -> list[dict]:
    """
    No-op unless `drawing` is a master unit with instance_count != 1 —
    every existing caller of extract_rows() keeps working unchanged for
    every drawing that isn't part of a repeating group.
    """
    mu = get_master_unit(db, drawing.id)
    if not mu or mu.instance_count == 1:
        return rows
    return [
        {**r, "quantity": round(r["quantity"] * mu.instance_count, 4), "master_unit_multiplier": mu.instance_count}
        for r in rows
    ]


def master_unit_to_dict(mu: "models.MasterUnit", drawing_name: str) -> dict:
    return {
        "id": mu.id,
        "project_id": mu.project_id,
        "drawing_id": mu.drawing_id,
        "drawing_name": drawing_name,
        "name": mu.name,
        "instance_count": mu.instance_count,
        "notes": mu.notes,
        "created_at": mu.created_at.isoformat() if mu.created_at else None,
    }
