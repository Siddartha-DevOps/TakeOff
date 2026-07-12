"""
Golden-set eval harness: score a model's predictions against fixed ground truth
and apply the promotion gate.

Dataset format — a JSON list of per-sheet samples:

    [
      {
        "image_id": "A-101",
        "rooms":   {"gt": [ring, ...], "pred": [ring, ...]},        # mIoU
        "symbols": {"gt":   {"door": [box, ...], ...},
                    "pred": {"door": [{"score": 0.9, "geom": box}, ...], ...}},  # mAP@0.5
        "quantities": {"gt":   {"floor_area_sqft": 4280, "wall_lf": 312, "door_count": 14},
                       "pred": {"floor_area_sqft": 4310, "wall_lf": 305, "door_count": 14}}
      }, ...
    ]

`ring` = [[x, y], ...]; `box` = [x1, y1, x2, y2] (plan-space).

Aggregation:
  - **mIoU**: mean over samples of per-sample room mean-IoU.
  - **mAP@0.5**: real, image-scoped global AP per class (a prediction can only
    match GT in its own image), then averaged over classes.
  - **measurement error %**: per quantity key, sum|pred-gt| / sum|gt| across
    samples (aggregate MAPE), then mean over keys.

The gate uses the reaudit's defensible targets (tunable): mIoU >= 0.70,
mAP >= 0.50, measurement error <= 5%.

    python -m ml.eval.harness --dataset golden.json [--report out.json]
    # exit code 0 if the gate passes, 1 if it fails
"""

from __future__ import annotations

import json
from typing import Optional

import numpy as np

from .metrics import ap_from_pr_curve, box_iou, mean_iou, measurement_error_pct

# Defensible release targets (memory/TOGAL_PARITY_REAUDIT.md §5). Real mAP is a
# harder number than the live harness's precision proxy, so its gate is lower.
GOLDEN_THRESHOLDS = {
    "min_miou": 0.70,
    "min_map": 0.50,
    "max_measurement_error_pct": 5.0,
}


def _aggregate_miou(samples: list[dict]) -> tuple[Optional[float], int]:
    vals = []
    for s in samples:
        rooms = s.get("rooms") or {}
        m = mean_iou(rooms.get("gt") or [], rooms.get("pred") or [])
        if m is not None:
            vals.append(m)
    return (round(float(np.mean(vals)), 4) if vals else None), len(vals)


def _global_map(samples: list[dict], iou_thr: float = 0.5) -> tuple[Optional[float], int]:
    """Image-scoped global mAP@iou_thr over all symbol classes with ground truth."""
    classes: set[str] = set()
    for s in samples:
        sym = s.get("symbols") or {}
        classes |= set((sym.get("gt") or {}).keys())
        classes |= set((sym.get("pred") or {}).keys())

    aps: list[float] = []
    for cls in sorted(classes):
        n_gt = sum(len(((s.get("symbols") or {}).get("gt") or {}).get(cls, [])) for s in samples)
        if n_gt == 0:
            continue
        # (score, sample_index, geom), sorted by score desc across all images.
        entries = []
        for si, s in enumerate(samples):
            for p in ((s.get("symbols") or {}).get("pred") or {}).get(cls, []):
                entries.append((p["score"], si, p["geom"]))
        entries.sort(key=lambda e: -e[0])

        matched = {si: [False] * len(((s.get("symbols") or {}).get("gt") or {}).get(cls, []))
                   for si, s in enumerate(samples)}
        tp = np.zeros(len(entries))
        fp = np.zeros(len(entries))
        for i, (_score, si, geom) in enumerate(entries):
            gts = ((samples[si].get("symbols") or {}).get("gt") or {}).get(cls, [])
            best, bj = 0.0, -1
            for j, g in enumerate(gts):
                if matched[si][j]:
                    continue
                iou = box_iou(geom, g)
                if iou > best:
                    best, bj = iou, j
            if best >= iou_thr and bj >= 0:
                matched[si][bj] = True
                tp[i] = 1
            else:
                fp[i] = 1

        tp_c, fp_c = np.cumsum(tp), np.cumsum(fp)
        recalls = tp_c / n_gt
        precisions = tp_c / np.maximum(tp_c + fp_c, np.finfo(np.float64).eps)
        aps.append(ap_from_pr_curve(recalls, precisions))

    return (round(float(np.mean(aps)), 4) if aps else None), len(aps)


def _aggregate_measurement_error(samples: list[dict]) -> tuple[Optional[float], int]:
    """Aggregate MAPE: per key, sum|pred-gt|/sum|gt| across samples, then mean over keys."""
    num: dict[str, float] = {}
    den: dict[str, float] = {}
    for s in samples:
        q = s.get("quantities") or {}
        gt, pred = q.get("gt") or {}, q.get("pred") or {}
        for key, g in gt.items():
            if g == 0:
                continue
            num[key] = num.get(key, 0.0) + abs(pred.get(key, 0.0) - g)
            den[key] = den.get(key, 0.0) + abs(g)
    per_key = [num[k] / den[k] * 100.0 for k in den if den[k] > 0]
    return (round(float(np.mean(per_key)), 2) if per_key else None), len(per_key)


def gate(metrics: dict, thresholds: Optional[dict] = None) -> tuple[bool, list[str]]:
    """Pass/fail against thresholds. A metric with no samples fails closed."""
    t = {**GOLDEN_THRESHOLDS, **(thresholds or {})}
    reasons: list[str] = []

    def _min(key, label, floor):
        v = metrics.get(key)
        if v is None:
            reasons.append(f"{label}: no samples to evaluate")
        elif v < floor:
            reasons.append(f"{label} {v} < required {floor}")

    def _max(key, label, ceil):
        v = metrics.get(key)
        if v is None:
            reasons.append(f"{label}: no samples to evaluate")
        elif v > ceil:
            reasons.append(f"{label} {v}% > allowed {ceil}%")

    _min("miou", "mIoU", t["min_miou"])
    _min("map", "mAP@0.5", t["min_map"])
    _max("measurement_error_pct", "measurement error", t["max_measurement_error_pct"])
    return (len(reasons) == 0), reasons


def evaluate(samples: list[dict], thresholds: Optional[dict] = None) -> dict:
    """Run the full golden-set evaluation and gate; return a report dict."""
    miou, miou_n = _aggregate_miou(samples)
    map_score, map_n = _global_map(samples)
    err, err_n = _aggregate_measurement_error(samples)
    metrics = {
        "miou": miou, "miou_sample_size": miou_n,
        "map": map_score, "map_classes": map_n,
        "measurement_error_pct": err, "measurement_error_keys": err_n,
        "n_samples": len(samples),
    }
    passed, reasons = gate(metrics, thresholds)
    return {
        "metrics": metrics,
        "gate_passed": passed,
        "gate_reasons": reasons,
        "thresholds": {**GOLDEN_THRESHOLDS, **(thresholds or {})},
    }


def evaluate_dataset_file(path: str, thresholds: Optional[dict] = None) -> dict:
    with open(path) as f:
        samples = json.load(f)
    return evaluate(samples, thresholds)


def _main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Golden-set eval harness + promotion gate")
    ap.add_argument("--dataset", required=True, help="JSON list of golden samples")
    ap.add_argument("--report", help="Write the JSON report here")
    ap.add_argument("--min-miou", type=float)
    ap.add_argument("--min-map", type=float)
    ap.add_argument("--max-error", type=float)
    args = ap.parse_args()

    thresholds = {}
    if args.min_miou is not None:
        thresholds["min_miou"] = args.min_miou
    if args.min_map is not None:
        thresholds["min_map"] = args.min_map
    if args.max_error is not None:
        thresholds["max_measurement_error_pct"] = args.max_error

    report = evaluate_dataset_file(args.dataset, thresholds or None)
    text = json.dumps(report, indent=2)
    print(text)
    if args.report:
        with open(args.report, "w") as f:
            f.write(text)
    return 0 if report["gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())
