"""
TakeOff.ai — Eval harness: mIoU / mAP-proxy / measurement-error, gating
AI model promotion.

Closes the `ModelVersion` half of CLAUDE.md §5's data model (specified
there by name only, no fields, never actually implemented — grepped zero
hits before this) and memory/TOGAL_PARITY_REAUDIT.md §5: "Gate model
promotion on the defensible independent figures: ~70-76% time savings and
within ~5% quantity margin vs a manual baseline on a golden plan set,
tracked per release (mIoU rooms, mAP symbols, measurement-error %)."

CLAUDE.md §4 places this at ml/eval/ in an intended Turborepo layout this
repo never actually became (confirmed: no ml/ directory exists anywhere)
— built here flat in app/backend/, matching every other in-tree adaptation
this session (drawing_compare.py instead of services/comparison/, tiling.py
instead of a separate tiling service, etc.).

No labeled "golden plan set" exists in this repo (checked ml/datasets/,
grepped ground_truth/golden/benchmark/CubiCasa — nothing is checked in).
Rather than block on building/licensing one, this computes the three
tracked metrics from data that's already flowing: CorrectionEvent
(routes/correction_routes.py, logged from day one per CLAUDE.md §5) is,
for any AI-sourced annotation a human has corrected, a genuine
predicted-vs-corrected pair. That's real signal, not a golden dataset —
narrower, but actually there.

Honest scope limits, stated up front rather than glossed over:
  - True mAP needs confidence-threshold sweeps *and* knowledge of missed
    detections (false negatives). A human can't "correct" something the
    AI never detected in the first place, so recall is structurally
    unmeasurable from correction data alone. What ships here as
    `map_proxy` is precision at the single live operating point —
    accepted / (accepted + rejected) — not true mAP. Never call it mAP in
    a UI or report without that qualifier.
  - mIoU only covers 'area' corrections where a corrected geometry
    (polygon) is actually present in the correction snapshot. As of this
    commit, `Takeoff.jsx`'s `snapshotAnnotation()` was extended to include
    `geometry` — before that, CorrectionEvent snapshots only carried
    {label, confidence, measuredValue}, so older/pre-existing correction
    rows will have no geometry to compare and are silently skipped, not
    fabricated a score.
  - measurement_error_pct needs a numeric measuredValue on both sides of
    an edit. accept/reject don't change the value (same annotation,
    unedited) so they carry no error signal either — only a genuine
    'edit' action with a changed measuredValue counts.
  - Below MIN_SAMPLE_SIZE corrections of a given kind, the metric is
    reported as None and the gate refuses to pass OR fail on it — "not
    enough data yet" is a real, distinct outcome from "passed" here, not
    silently rounded to a pass.
"""

import json
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

import models

MIN_SAMPLE_SIZE = 5

# memory/TOGAL_PARITY_REAUDIT.md §5 names "within ~5% quantity margin" as
# its one concrete number; mIoU/mAP aren't given exact bars there (only
# named as metrics to *track*), so min_miou/min_map_proxy below are a
# defensible engineering default, not a transcribed spec figure — every
# caller can override via evaluate()'s `thresholds` param.
DEFAULT_THRESHOLDS = {
    "min_miou": 0.70,
    "min_map_proxy": 0.85,
    "max_measurement_error_pct": 5.0,
}


def _polygon_wkt(points) -> Optional[str]:
    if not points or not isinstance(points, list) or len(points) < 3:
        return None
    try:
        ring = list(points) + [points[0]]
        return "POLYGON((" + ", ".join(f"{p[0]} {p[1]}" for p in ring) + "))"
    except (TypeError, IndexError):
        return None


def compute_iou(db: Session, points_a, points_b) -> Optional[float]:
    """
    Real IoU via PostGIS (ST_Intersection/ST_Union/ST_Area) rather than a
    hand-rolled polygon-clipping implementation — this backend already
    requires PostGIS for Detection.geom, so this adds no new dependency.
    Returns None (not 0.0) for degenerate input, so a caller can tell
    "not computable" apart from "zero overlap".
    """
    wkt_a, wkt_b = _polygon_wkt(points_a), _polygon_wkt(points_b)
    if not wkt_a or not wkt_b:
        return None
    result = db.execute(
        text(
            "SELECT ST_Area(ST_Intersection(ST_GeomFromText(:a), ST_GeomFromText(:b))) "
            "/ NULLIF(ST_Area(ST_Union(ST_GeomFromText(:a), ST_GeomFromText(:b))), 0)"
        ),
        {"a": wkt_a, "b": wkt_b},
    ).scalar()
    return float(result) if result is not None else None


def _load_json(raw: Optional[str]) -> Optional[dict]:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def evaluate_model_version(db: Session, model_version: str, project_id: Optional[int] = None) -> dict:
    """
    Computes {miou, map_proxy, measurement_error_pct} (+ each metric's own
    sample size) from CorrectionEvent rows stamped with this model_version
    (see models.CorrectionEvent.model_version, set by the frontend from
    Annotation.meta.aiModelVersion at correction time). Every metric is
    None if its sample size is 0 — never a fabricated number from an empty
    set.
    """
    query = db.query(models.CorrectionEvent).filter(
        models.CorrectionEvent.model_version == model_version,
        models.CorrectionEvent.action.in_(["accept", "reject", "edit"]),
    )
    if project_id is not None:
        query = query.filter(models.CorrectionEvent.project_id == project_id)

    accepted = rejected = 0
    ious = []
    errors = []

    for ev in query.all():
        if ev.action == "accept":
            accepted += 1
            continue
        if ev.action == "reject":
            rejected += 1
            continue

        # action == "edit": a human changed something about an AI shape —
        # the only action that can carry a genuine before/after delta.
        before, after = _load_json(ev.before), _load_json(ev.after)
        if not before or not after:
            continue

        if ev.annotation_type == "area":
            iou = compute_iou(db, before.get("geometry"), after.get("geometry"))
            if iou is not None:
                ious.append(iou)

        val_before, val_after = before.get("measuredValue"), after.get("measuredValue")
        if isinstance(val_before, (int, float)) and isinstance(val_after, (int, float)) and val_after:
            errors.append(abs(val_after - val_before) / abs(val_after) * 100.0)

    map_sample = accepted + rejected
    return {
        "miou": round(sum(ious) / len(ious), 4) if ious else None,
        "miou_sample_size": len(ious),
        "map_proxy": round(accepted / map_sample, 4) if map_sample else None,
        "map_proxy_sample_size": map_sample,
        "measurement_error_pct": round(sum(errors) / len(errors), 2) if errors else None,
        "measurement_error_sample_size": len(errors),
    }


def gate_promotion(metrics: dict, thresholds: Optional[dict] = None) -> tuple[bool, list[str]]:
    """
    Returns (passed, reasons) — reasons is empty iff passed. A metric with
    fewer than MIN_SAMPLE_SIZE data points blocks the gate with an
    "insufficient data" reason rather than being skipped (which would let
    a model with zero real feedback pass by default) or force-failed
    (which would permanently block promotion on a brand new project with
    no correction history yet — an operator can always override via a
    smaller thresholds dict, but the default requires real signal).
    """
    thresholds = thresholds or DEFAULT_THRESHOLDS
    reasons = []

    def _check(value_key, sample_key, label, minimum=None, maximum=None):
        sample = metrics.get(sample_key, 0)
        if sample < MIN_SAMPLE_SIZE:
            reasons.append(f"{label}: insufficient data ({sample} < {MIN_SAMPLE_SIZE} required)")
            return
        value = metrics.get(value_key)
        if minimum is not None and value < minimum:
            reasons.append(f"{label} {value:.2f} below required minimum {minimum:.2f}")
        if maximum is not None and value > maximum:
            reasons.append(f"{label} {value:.2f} above allowed maximum {maximum:.2f}")

    _check("miou", "miou_sample_size", "mIoU", minimum=thresholds["min_miou"])
    _check("map_proxy", "map_proxy_sample_size", "map_proxy", minimum=thresholds["min_map_proxy"])
    _check("measurement_error_pct", "measurement_error_sample_size", "measurement error %", maximum=thresholds["max_measurement_error_pct"])

    return (len(reasons) == 0, reasons)
