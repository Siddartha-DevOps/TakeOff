"""
Release + deploy (Phase 5) — from a gated eval to a served model.

Composes the pieces built in earlier phases into one release path:

    golden.json
        │  ml.eval.harness.evaluate_dataset_file      (metrics + gate)
        ▼
    register  → ml.training.retrain.register_model_version   (card + ModelVersion row)
        │
    promote   → ml.eval.promote.apply_promotion             (single-ACTIVE invariant)
        │  (only if the gate passed)
        ▼
    deploy    → stage_weights → models/best.pt              (what ai.inference loads)
        │
    verify    → serving readiness (deps + weights present)

The ACTIVE-model resolution, weights staging, and readiness checks are pure /
filesystem and unit-tested; ``release`` itself touches the DB (reusing existing
registration) and is driven by the CLI on the training/release box.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Optional

from ml.preflight import run_preflight
from ml.training.config import TASK_WEIGHTS


def pick_active(rows: list) -> Optional[str]:
    """Return the ACTIVE row's weights_uri from ``[{stage, weights_uri}, ...]`` or None.

    Pure — the single source of truth for "which weights should be served".
    """
    for r in rows:
        if r.get("stage") == "ACTIVE":
            return r.get("weights_uri")
    return None


def resolve_active_weights(db, name: str) -> Optional[str]:
    """Query the ACTIVE ModelVersion's weights_uri for a model line (lazy DB)."""
    import models

    rows = (
        db.query(models.ModelVersion)
        .filter(models.ModelVersion.name == name)
        .all()
    )
    serialized = [{"stage": getattr(getattr(r, "stage", None), "name", None),
                   "weights_uri": getattr(r, "weights_uri", None)} for r in rows]
    return pick_active(serialized)


def stage_weights(source: str | Path, target: str | Path = None, *, task: str = "spaces") -> Path:
    """Copy trained weights to the stable inference path the engine loads.

    ``source`` is a local weights file (a remote object-storage URI is resolved
    by the deployment's init-container / storage layer before this runs). Creates
    parent dirs. Defaults ``target`` to the task's contract path.
    """
    source = Path(source)
    if not source.is_file():
        raise FileNotFoundError(f"weights not found: {source}")
    target = Path(target) if target else TASK_WEIGHTS[task]
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target


def serving_readiness(*, task: str = "spaces", weights_path: str | Path = None) -> dict:
    """Is the box ready to serve? (deps importable + weights present at the path.)

    Returns ``{"ready", "blockers", "weights"}`` — the deploy-time equivalent of
    ``preflight --require serve``.
    """
    wp = Path(weights_path) if weights_path else TASK_WEIGHTS[task]
    r = run_preflight(weights_path=wp)
    return {"ready": r.can_serve, "blockers": r.blockers, "weights": r.weights}


def release(db, *, name: str, version: str, task: str, golden_path: str | Path,
            weights_uri: Optional[str] = None, thresholds: Optional[dict] = None,
            stage_from: Optional[str | Path] = None) -> dict:
    """Full gated release: evaluate → register → promote (single-ACTIVE) → stage.

    Registers the version regardless of outcome (CANDIDATE if it fails the gate);
    only a passing model is promoted ACTIVE, demotes the prior ACTIVE, and — when
    ``stage_from`` is given — has its weights staged to the inference path.
    """
    from ml.eval.harness import evaluate_dataset_file
    from ml.eval.promote import apply_promotion
    from ml.training.retrain import register_model_version

    report = evaluate_dataset_file(str(golden_path), thresholds)
    passed = bool(report["gate_passed"])

    register_model_version(db, name=name, version=version, task=task,
                           report=report, weights_uri=weights_uri)
    plan = apply_promotion(db, name=name, new_version=version, passed=passed)

    staged = None
    if passed and stage_from:
        staged = str(stage_weights(stage_from, task=task))

    return {
        "version": version,
        "gate_passed": passed,
        "metrics": report["metrics"],
        "promotion": plan,
        "staged_to": staged,
        "serving": serving_readiness(task=task),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Release a gated model + verify serving readiness")
    sub = ap.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("verify", help="check serving readiness (deps + weights)")
    v.add_argument("--task", default="spaces", choices=sorted(TASK_WEIGHTS))
    v.add_argument("--weights", default=None)

    s = sub.add_parser("stage", help="copy trained weights to the inference path")
    s.add_argument("--from", dest="src", required=True)
    s.add_argument("--task", default="spaces", choices=sorted(TASK_WEIGHTS))

    args = ap.parse_args(argv)

    if args.cmd == "verify":
        r = serving_readiness(task=args.task, weights_path=args.weights)
        print(f"[release] serving ready={r['ready']}")
        for b in r["blockers"]:
            print(f"  - {b}")
        return 0 if r["ready"] else 1

    if args.cmd == "stage":
        target = stage_weights(args.src, task=args.task)
        print(f"[release] staged {args.src} -> {target}")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
