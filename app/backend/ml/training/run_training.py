"""
Training runner (Phase 3) — the production entrypoint for a YOLOv8-seg run.

Gated, config-driven, and honest about the environment:
  1. **Preflight gate** — refuses to train unless the dataset is present and (for
     a real run) the ML deps are importable. No silent no-op, no fake weights.
  2. **Run** — fine-tunes via ultralytics (lazy import) using ``TrainConfig``.
  3. **Promote** — copies the run's ``best.pt`` to the stable inference path
     (``models/best.pt`` for spaces), so ``ai.inference`` picks it up.

``--smoke`` runs a 1-epoch config to verify the pipeline end-to-end quickly.

The planning/promotion helpers are pure and unit-tested; only ``run`` touches
ultralytics/GPU, so this module imports and tests on a CPU-only CI box.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Optional

from ml.preflight import run_preflight
from ml.training.config import TrainConfig


def build_train_plan(config: TrainConfig, data_yaml: str | Path, *, require_deps: bool = True) -> dict:
    """Describe what a run would do and whether it's allowed to proceed.

    Returns ``{"ready", "blockers", "train_kwargs", "weights_target"}``. ``ready``
    is False (with blockers) when the dataset is missing/empty, or — when
    ``require_deps`` — the ML deps aren't importable. Pure aside from the
    filesystem/dep probes in preflight.
    """
    readiness = run_preflight(data_yaml=str(data_yaml))
    blockers: list[str] = []
    ds = readiness.dataset
    if not ds.get("exists"):
        blockers.append(f"dataset not found: {data_yaml}")
    elif ds.get("n_label_files", 0) == 0:
        blockers.append("dataset has no label files")
    if require_deps:
        for dep in ("torch", "ultralytics"):
            if not readiness.dependencies.get(dep):
                blockers.append(f"missing dependency: {dep} (pip install -r requirements-ml.txt)")
    return {
        "ready": not blockers,
        "blockers": blockers,
        "train_kwargs": config.train_kwargs(data_yaml),
        "weights_target": str(config.weights_target()),
    }


def resolve_best_weights(save_dir: str | Path) -> Optional[Path]:
    """Return the run's ``weights/best.pt`` (falling back to ``last.pt``), or None."""
    save_dir = Path(save_dir)
    for name in ("best.pt", "last.pt"):
        cand = save_dir / "weights" / name
        if cand.is_file():
            return cand
    return None


def promote_weights(best: str | Path, target: str | Path) -> Path:
    """Copy trained weights to the stable inference path, creating parent dirs."""
    best, target = Path(best), Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(best, target)
    return target


def run(config: TrainConfig, data_yaml: str | Path, *, promote: bool = True,
        require_deps: bool = True) -> dict:
    """Gate → train (ultralytics, lazy) → promote best.pt. Returns a result dict.

    Raises ``RuntimeError`` if the preflight gate fails — never trains on a
    missing dataset or fabricates weights.
    """
    config.validate()
    plan = build_train_plan(config, data_yaml, require_deps=require_deps)
    if not plan["ready"]:
        raise RuntimeError("training blocked: " + "; ".join(plan["blockers"]))

    from ultralytics import YOLO  # lazy — GPU box only
    from ai.inference.device import resolve_device

    device = resolve_device(config.device).device
    kwargs = config.train_kwargs(data_yaml, device=device)
    print(f"[train] task={config.task} device={device} epochs={config.epochs} imgsz={config.imgsz}")

    model = YOLO(config.base_model)
    results = model.train(**kwargs)

    best = resolve_best_weights(results.save_dir)
    if best is None:
        raise RuntimeError(f"training finished but no weights found under {results.save_dir}")

    target = None
    if promote:
        target = promote_weights(best, config.weights_target())
        print(f"[train] promoted {best} -> {target}")

    return {
        "task": config.task,
        "device": device,
        "save_dir": str(results.save_dir),
        "best_weights": str(best),
        "promoted_to": str(target) if target else None,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Train a TakeOff.ai YOLOv8-seg model")
    ap.add_argument("--data", required=True, help="path to dataset data.yaml")
    ap.add_argument("--task", default="spaces", choices=["spaces", "symbols"])
    ap.add_argument("--epochs", type=int, default=None)
    ap.add_argument("--imgsz", type=int, default=None)
    ap.add_argument("--batch", type=int, default=None)
    ap.add_argument("--base-model", default=None)
    ap.add_argument("--device", default=None)
    ap.add_argument("--smoke", action="store_true", help="1-epoch pipeline check (not for accuracy)")
    ap.add_argument("--no-promote", action="store_true", help="train without copying best.pt to the inference path")
    ap.add_argument("--dry-run", action="store_true", help="print the gated plan and exit (no training)")
    args = ap.parse_args(argv)

    config = TrainConfig.smoke(task=args.task) if args.smoke else TrainConfig(task=args.task)
    for attr, val in (("epochs", args.epochs), ("imgsz", args.imgsz),
                      ("batch", args.batch), ("base_model", args.base_model), ("device", args.device)):
        if val is not None:
            setattr(config, attr, val)
    config.validate()

    if args.dry_run:
        plan = build_train_plan(config, args.data)
        print(f"[train] ready={plan['ready']}")
        for b in plan["blockers"]:
            print(f"  - blocker: {b}")
        print(f"[train] weights_target={plan['weights_target']}")
        return 0 if plan["ready"] else 1

    try:
        result = run(config, args.data, promote=not args.no_promote)
    except RuntimeError as exc:
        print(f"[train] {exc}")
        return 1
    print(f"[train] done: {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
