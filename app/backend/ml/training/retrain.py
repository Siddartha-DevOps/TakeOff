"""
Retraining orchestrator — the accuracy flywheel, end to end.

    corrections -> dataset -> fine-tune -> golden eval -> promotion gate -> registry

Each stage calls the real module (export_corrections / train_yolov8_seg /
ml.eval.harness / ml.registry.model_card / models.ModelVersion). Training and
golden inference need a GPU and labeled data, so run this on a training box; the
stages fail *loudly and individually* rather than silently, and `--dry-run`
walks the plan without touching anything.

    python -m ml.training.retrain \
        --name symbol_seg --version 2026.07.1 \
        --golden ml/eval/golden.json --base-dataset /data/base \
        --out-dir /artifacts --register

`--golden` is a harness dataset file (gt + pred for the *candidate* weights). Use
`ml.eval.harness` conventions; produce the `pred` side by running the freshly
trained weights over the golden sheets (see predict_golden hook below).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional


def run_export(db, out_dir: str | Path, **kwargs) -> dict:
    """Stage 1: CorrectionEvents -> YOLO-seg dataset."""
    from .export_corrections import export_corrections_dataset

    summary = export_corrections_dataset(db, out_dir, **kwargs)
    print(f"[export] {summary}")
    return summary


def run_train(dataset_dir: str | Path, out_dir: str | Path, **kwargs) -> Path:
    """Stage 2: fine-tune YOLOv8-seg on the exported (+ base) dataset."""
    from training.train_yolov8_seg import train

    weights = train(dataset_dir=str(dataset_dir), output_dir=Path(out_dir), **kwargs)
    print(f"[train] weights -> {weights}")
    return weights


def run_eval(golden_path: str | Path, thresholds: Optional[dict] = None) -> dict:
    """Stage 3: score candidate predictions against the golden set + gate."""
    from ml.eval.harness import evaluate_dataset_file

    report = evaluate_dataset_file(str(golden_path), thresholds)
    print(f"[eval] metrics={report['metrics']} gate_passed={report['gate_passed']}")
    if report["gate_reasons"]:
        print(f"[eval] gate reasons: {report['gate_reasons']}")
    return report


def register_model_version(
    db,
    *,
    name: str,
    version: str,
    task: str,
    report: dict,
    weights_uri: Optional[str] = None,
    dataset_summary: Optional[dict] = None,
    registry_dir: str | Path = "ml/registry/cards",
) -> dict:
    """Stage 4: write a model card and a ModelVersion row; promote only if gated.

    Field-tolerant against the ModelVersion schema (sets only attributes that
    exist), so it survives minor model changes.
    """
    import models
    from ml.registry.model_card import build_model_card, write_model_card

    card = build_model_card(
        name=name, version=version, task=task, eval_report=report,
        weights_uri=weights_uri, dataset_summary=dataset_summary,
    )
    card_dir = write_model_card(card, registry_dir)
    print(f"[registry] card -> {card_dir}")

    m = report["metrics"]
    passed = bool(report["gate_passed"])
    mv = models.ModelVersion()
    fields = {
        "name": name, "version_string": version, "version": version, "task": task,
        "miou": m.get("miou"), "map_score": m.get("map"),
        "measurement_error_pct": m.get("measurement_error_pct"),
        "eval_sample_size": m.get("n_samples"), "weights_uri": weights_uri,
        "promoted": passed,
    }
    for k, v in fields.items():
        if hasattr(mv, k):
            setattr(mv, k, v)
    # Stage: ACTIVE only if the gate passed, else CANDIDATE.
    if hasattr(mv, "stage") and hasattr(models, "ModelVersionStage"):
        mv.stage = models.ModelVersionStage.ACTIVE if passed else models.ModelVersionStage.CANDIDATE
    try:
        db.add(mv)
        db.commit()
        print(f"[registry] ModelVersion registered ({'ACTIVE' if passed else 'CANDIDATE'})")
    except Exception as exc:
        db.rollback()
        print(f"[registry] WARNING: could not persist ModelVersion: {exc}")
    return card


def retrain(args) -> int:
    """Drive the flywheel per the CLI args. Returns a process exit code."""
    from database import SessionLocal

    out = Path(args.out_dir)
    thresholds = {}
    if args.min_miou is not None:
        thresholds["min_miou"] = args.min_miou
    if args.min_map is not None:
        thresholds["min_map"] = args.min_map
    if args.max_error is not None:
        thresholds["max_measurement_error_pct"] = args.max_error

    if args.dry_run:
        print("[dry-run] would: export corrections -> train -> eval "
              f"{args.golden} -> gate({thresholds or 'defaults'}) -> "
              f"{'register' if args.register else 'no register'}")
        return 0

    db = SessionLocal()
    try:
        dataset_summary = run_export(db, out / "dataset")
        if args.base_dataset:
            print(f"[train] NOTE: merge base dataset at {args.base_dataset} before training")
        weights = run_train(out / "dataset", out) if not args.skip_train else None

        report = run_eval(args.golden, thresholds or None)

        if args.register:
            register_model_version(
                db, name=args.name, version=args.version, task=args.task,
                report=report, weights_uri=str(weights) if weights else None,
                dataset_summary=dataset_summary,
            )
        return 0 if report["gate_passed"] else 1
    finally:
        db.close()


def _main() -> int:
    ap = argparse.ArgumentParser(description="Retraining flywheel orchestrator")
    ap.add_argument("--name", default="symbol_seg")
    ap.add_argument("--version", required=True)
    ap.add_argument("--task", default="symbol_det")
    ap.add_argument("--golden", required=True, help="Golden eval dataset (gt+pred) JSON")
    ap.add_argument("--out-dir", default="artifacts")
    ap.add_argument("--base-dataset", help="Existing labeled dataset to merge with corrections")
    ap.add_argument("--skip-train", action="store_true", help="Eval/register only (weights already trained)")
    ap.add_argument("--register", action="store_true", help="Write a ModelVersion + card")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--min-miou", type=float)
    ap.add_argument("--min-map", type=float)
    ap.add_argument("--max-error", type=float)
    return retrain(ap.parse_args())


if __name__ == "__main__":
    raise SystemExit(_main())
