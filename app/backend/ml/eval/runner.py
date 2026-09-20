"""Evidence-only evaluation runner for a fixed, labeled benchmark.

The runner consumes already-produced predictions; model execution stays in the
framework-specific adapter.  This keeps metric calculation reproducible and
lets a report explicitly remain NOT_EVALUATED until both GT and predictions
exist.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from shapely.geometry import Polygon

from .metrics import poly_iou


def polygon_dice(left: list, right: list) -> float:
    a, b = Polygon(left), Polygon(right)
    if not a.is_valid:
        a = a.buffer(0)
    if not b.is_valid:
        b = b.buffer(0)
    denominator = a.area + b.area
    return float(2 * a.intersection(b).area / denominator) if denominator else 0.0


def _match(predictions: list[dict], ground_truth: list[dict], threshold: float) -> tuple[list[tuple[int, int, float]], int, int]:
    candidates: list[tuple[float, int, int]] = []
    for pi, prediction in enumerate(predictions):
        for gi, truth in enumerate(ground_truth):
            if prediction["class"] == truth["class"]:
                candidates.append((poly_iou(prediction["geometry"], truth["geometry"]), pi, gi))
    matches: list[tuple[int, int, float]] = []
    used_predictions: set[int] = set()
    used_truth: set[int] = set()
    for iou, pi, gi in sorted(candidates, reverse=True):
        if iou < threshold or pi in used_predictions or gi in used_truth:
            continue
        matches.append((pi, gi, iou))
        used_predictions.add(pi)
        used_truth.add(gi)
    return matches, len(predictions) - len(used_predictions), len(ground_truth) - len(used_truth)


def _ratio_error(predicted: float, truth: float) -> float | None:
    return abs(predicted - truth) / truth * 100.0 if truth else None


def evaluate_samples(samples: list[dict[str, Any]], *, iou_threshold: float = 0.5) -> dict[str, Any]:
    per_image: list[dict[str, Any]] = []
    totals = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    all_ious: list[float] = []
    all_dice: list[float] = []
    area_errors: list[float] = []
    perimeter_errors: list[float] = []
    exact_counts = 0

    for sample in samples:
        truth = sample.get("ground_truth") or []
        predictions = sample.get("predictions") or []
        matches, fp, fn = _match(predictions, truth, iou_threshold)
        matched_pred = {pi for pi, _, _ in matches}
        matched_truth = {gi for _, gi, _ in matches}
        for pi, gi, iou in matches:
            label = truth[gi]["class"]
            totals[label]["tp"] += 1
            all_ious.append(iou)
            all_dice.append(polygon_dice(predictions[pi]["geometry"], truth[gi]["geometry"]))
        for pi, prediction in enumerate(predictions):
            if pi not in matched_pred:
                totals[prediction["class"]]["fp"] += 1
        for gi, item in enumerate(truth):
            if gi not in matched_truth:
                totals[item["class"]]["fn"] += 1

        gt_polygons = [Polygon(item["geometry"]) for item in truth]
        pred_polygons = [Polygon(item["geometry"]) for item in predictions]
        area_error = _ratio_error(sum(p.area for p in pred_polygons), sum(p.area for p in gt_polygons))
        perimeter_error = _ratio_error(sum(p.length for p in pred_polygons), sum(p.length for p in gt_polygons))
        if area_error is not None:
            area_errors.append(area_error)
        if perimeter_error is not None:
            perimeter_errors.append(perimeter_error)
        exact = len(predictions) == len(truth)
        exact_counts += int(exact)
        per_image.append({
            "image_id": sample.get("image_id"),
            "ground_truth_count": len(truth), "prediction_count": len(predictions),
            "true_positive": len(matches), "false_positive": fp, "false_negative": fn,
            "room_count_exact": exact,
            "room_count_absolute_error": abs(len(predictions) - len(truth)),
            "area_error_pct": area_error, "perimeter_error_pct": perimeter_error,
            "mean_iou": mean(iou for _, _, iou in matches) if matches else 0.0,
            "mean_dice": mean(polygon_dice(predictions[pi]["geometry"], truth[gi]["geometry"])
                              for pi, gi, _ in matches) if matches else 0.0,
        })

    per_class = {}
    for label, counts in sorted(totals.items()):
        tp, fp, fn = counts["tp"], counts["fp"], counts["fn"]
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        per_class[label] = {**counts, "precision": precision, "recall": recall,
                            "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0}

    tp = sum(item["tp"] for item in totals.values())
    fp = sum(item["fp"] for item in totals.values())
    fn = sum(item["fn"] for item in totals.values())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "evaluation_status": "EVALUATED" if samples else "NOT_EVALUATED",
        "iou_threshold": iou_threshold,
        "per_image": per_image,
        "aggregate": {
            "sample_count": len(samples), "precision": precision, "recall": recall,
            "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
            "mean_iou": mean(all_ious) if all_ious else None,
            "mean_dice": mean(all_dice) if all_dice else None,
            "room_count_accuracy": exact_counts / len(samples) if samples else None,
            "mean_area_error_pct": mean(area_errors) if area_errors else None,
            "mean_perimeter_error_pct": mean(perimeter_errors) if perimeter_errors else None,
            "per_class": per_class,
        },
    }


def evaluate_file(path: str | Path, *, output_path: str | Path | None = None, iou_threshold: float = 0.5) -> dict:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    samples = payload.get("samples", payload) if isinstance(payload, dict) else payload
    report = evaluate_samples(samples, iou_threshold=iou_threshold)
    if output_path:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report
