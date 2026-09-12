#!/usr/bin/env python3
"""
TakeOff.ai — offline eval harness for candidate model checkpoints.

Three eval mechanisms now exist in this repo; this is the cheapest/first
of them, not a replacement for either of the other two:
  1. THIS SCRIPT — plain `ultralytics model.val()` against a held-out
     split (e.g. produced by scripts/cubicasa_to_coco.py). Cheapest,
     fastest signal on a freshly-trained checkpoint; no golden set or
     Postgres needed. Good for "did this training run even work" before
     spending a golden-set eval on it.
  2. app/backend/ml/eval/harness.py — the sanctioned release gate
     (`python -m ml.eval.harness`), scored against a fixed labeled
     *golden* plan set (mIoU / mAP@0.5 / measurement-error %, see
     app/backend/ml/README.md). This is what actually promotes a
     ModelVersion in app/backend/ml/training/retrain.py's flywheel —
     run it before shipping a checkpoint, not this script.
  3. app/backend/eval_harness.py — computes the same style of metrics
     from live CorrectionEvent data instead of a fixed set: production
     accuracy, drifting as real users correct real AI output, answering
     "is what's already shipped still good" rather than "is this new
     checkpoint good enough to ship."

Targets are transcribed from AI_TRAINING_GUIDE.md's per-feature table.
symbols.yaml trains door+window+MEP as one combined detector, so the
combined gate uses MEP's numbers (the weakest of the three sub-tasks) —
per-class mAP is also printed so door/window/MEP can each be checked
against their own row in that table individually.

Usage:
    python scripts/evaluate.py --model runs/blueprint_seg/weights/best.pt \
        --data datasets/rooms.yaml --task rooms

    python scripts/evaluate.py --model app/backend/ai/models/symbol_counts/yolov8-seg.pt \
        --data datasets/symbols.yaml --task symbols

    python scripts/evaluate.py --task all --rooms-model models/rooms_v1.pt

Exit code is non-zero if any evaluated task misses its target — meant to
gate a CI/CD promotion step, not just print a report.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

RUNS_DIR = Path(__file__).resolve().parent.parent / "runs" / "eval"

TARGETS = {
    "rooms": {"mAP50": 0.88, "mAP50_95": 0.72},
    "symbols": {"mAP50": 0.85, "mAP50_95": 0.68},  # MEP row — weakest sub-task, see module docstring
}

PER_CLASS_TARGETS = {
    # class name -> (mAP50 target, source feature in AI_TRAINING_GUIDE.md)
    "standard_door": (0.91, "Feature 2: Door detection"),
    "bifold_door": (0.91, "Feature 2: Door detection"),
    "sliding_door": (0.91, "Feature 2: Door detection"),
    "double_door": (0.91, "Feature 2: Door detection"),
    "pocket_door": (0.91, "Feature 2: Door detection"),
    "fixed_window": (0.89, "Feature 3: Window detection"),
    "casement_window": (0.89, "Feature 3: Window detection"),
    "sliding_window": (0.89, "Feature 3: Window detection"),
    "transom_window": (0.89, "Feature 3: Window detection"),
    "bay_window": (0.89, "Feature 3: Window detection"),
    "toilet": (0.85, "Feature 5: MEP symbols"),
    "sink": (0.85, "Feature 5: MEP symbols"),
    "shower": (0.85, "Feature 5: MEP symbols"),
    "bathtub": (0.85, "Feature 5: MEP symbols"),
}


def run_eval(model_path: str, data_yaml: str, device: str = "0") -> dict:
    from ultralytics import YOLO

    model = YOLO(model_path)
    metrics = model.val(data=data_yaml, device=device, verbose=False)

    per_class = {}
    names = metrics.names if hasattr(metrics, "names") else {}
    try:
        map50_per_class = metrics.box.ap50
        for idx, name in names.items():
            if idx < len(map50_per_class):
                per_class[name] = float(map50_per_class[idx])
    except Exception:
        pass  # segmentation-only runs may not expose box.ap50 per class the same way

    return {
        "mAP50": float(metrics.box.map50),
        "mAP50_95": float(metrics.box.map),
        "precision": float(metrics.box.p.mean()) if len(metrics.box.p) else None,
        "recall": float(metrics.box.r.mean()) if len(metrics.box.r) else None,
        "per_class_mAP50": per_class,
    }


def check_targets(task: str, results: dict) -> bool:
    target = TARGETS[task]
    passed = True
    print(f"\n=== {task} — overall ===")
    for metric, target_value in target.items():
        value = results.get(metric)
        ok = value is not None and value >= target_value
        passed = passed and ok
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {metric}: {value if value is not None else 'n/a'} (target >= {target_value})")

    per_class = results.get("per_class_mAP50", {})
    if per_class:
        print(f"=== {task} — per-class mAP50 (AI_TRAINING_GUIDE.md targets) ===")
        for cls_name, value in per_class.items():
            target_info = PER_CLASS_TARGETS.get(cls_name)
            if not target_info:
                print(f"  {cls_name}: {value:.3f} (no per-class target defined)")
                continue
            cls_target, source = target_info
            ok = value >= cls_target
            mark = "PASS" if ok else "FAIL"
            print(f"  [{mark}] {cls_name}: {value:.3f} (target >= {cls_target}, {source})")
    return passed


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--task", choices=["rooms", "symbols", "all"], default="all")
    parser.add_argument("--model", type=str, help="Checkpoint path (single-task mode)")
    parser.add_argument("--data", type=str, help="Path to data yaml (single-task mode)")
    parser.add_argument("--rooms-model", type=str, default="models/rooms_v1.pt")
    parser.add_argument("--rooms-data", type=str, default=str(Path(__file__).resolve().parent.parent / "datasets" / "rooms.yaml"))
    parser.add_argument("--symbols-model", type=str, default="app/backend/ai/models/symbol_counts/yolov8-seg.pt",
                         help="Default matches app/backend/training/train_yolov8_seg.py's DEFAULT_OUTPUT — the weights ai/detect_symbols.py actually loads.")
    parser.add_argument("--symbols-data", type=str, default=str(Path(__file__).resolve().parent.parent / "datasets" / "symbols.yaml"))
    parser.add_argument("--device", type=str, default="cpu")
    args = parser.parse_args()

    jobs = []
    if args.model and args.data:
        task = args.task if args.task != "all" else "rooms"
        jobs.append((task, args.model, args.data))
    else:
        if args.task in ("rooms", "all"):
            jobs.append(("rooms", args.rooms_model, args.rooms_data))
        if args.task in ("symbols", "all"):
            jobs.append(("symbols", args.symbols_model, args.symbols_data))

    all_results = {}
    overall_pass = True
    for task, model_path, data_yaml in jobs:
        if not Path(model_path).exists():
            print(f"SKIP {task}: checkpoint not found at {model_path}")
            overall_pass = False
            continue
        results = run_eval(model_path, data_yaml, device=args.device)
        all_results[task] = results
        overall_pass = check_targets(task, results) and overall_pass

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RUNS_DIR / f"eval_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    out_path.write_text(json.dumps({"results": all_results, "passed": overall_pass}, indent=2))
    print(f"\nResults written to {out_path}")

    sys.exit(0 if overall_pass else 1)


if __name__ == "__main__":
    main()
