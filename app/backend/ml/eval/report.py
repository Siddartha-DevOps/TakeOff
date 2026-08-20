"""
Accuracy report generator (Workstream 1C — the "proof").

Turns an ``ml.eval.harness`` report into a readable one-page accuracy card: the
three gate metrics vs their thresholds, a PASS/FAIL verdict, sample size, and —
when it fails — the specific reasons plus what to do next (label more of the weak
classes; the active-learning queue already ranks them). This is the artifact you
show a customer or attach to a `ModelVersion`.

Pure (formats a report dict) — unit-tested; the CLI runs the harness for you.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

_METRIC_ROWS = [
    ("mIoU (space segmentation)", "miou", "min_miou", "≥", "{:.3f}"),
    ("mAP@0.5 (symbol detection)", "map", "min_map", "≥", "{:.3f}"),
    ("Measurement error", "measurement_error_pct", "max_measurement_error_pct", "≤", "{:.2f}%"),
]


def _metric_ok(key: str, value, threshold) -> Optional[bool]:
    if value is None:
        return False
    if key == "measurement_error_pct":
        return value <= threshold
    return value >= threshold


def accuracy_report_dict(report: dict) -> dict:
    """Structured accuracy card from a harness report (for a ModelVersion / API)."""
    metrics = report.get("metrics", {})
    thresholds = report.get("thresholds", {})
    rows = []
    for label, mkey, tkey, op, _fmt in _METRIC_ROWS:
        val = metrics.get(mkey)
        thr = thresholds.get(tkey)
        rows.append({
            "metric": label, "key": mkey, "value": val,
            "threshold": thr, "op": op, "ok": _metric_ok(mkey, val, thr),
        })
    return {
        "gate_passed": bool(report.get("gate_passed")),
        "n_samples": metrics.get("n_samples"),
        "rows": rows,
        "reasons": report.get("reasons", []),
    }


def build_accuracy_report(report: dict, *, title: str = "TakeOff.ai — Model Accuracy Report") -> str:
    """Render a Markdown accuracy card from a harness report."""
    card = accuracy_report_dict(report)
    verdict = "✅ PASSED — cleared the promotion gate" if card["gate_passed"] else "❌ FAILED — not promotable yet"
    lines = [f"# {title}", "", f"**Gate:** {verdict}", ""]
    if card["n_samples"] is not None:
        lines.append(f"Evaluated on **{card['n_samples']}** golden sheets.\n")

    lines += ["| Metric | Result | Threshold | Status |", "|---|---|---|---|"]
    for label, mkey, tkey, op, fmt in _METRIC_ROWS:
        row = next(r for r in card["rows"] if r["key"] == mkey)
        val = fmt.format(row["value"]) if row["value"] is not None else "—"
        thr = row["threshold"]
        thr_str = (f"{op} {thr}%" if mkey == "measurement_error_pct" else f"{op} {thr}")
        lines.append(f"| {label} | {val} | {thr_str} | {'✅' if row['ok'] else '❌'} |")

    if not card["gate_passed"]:
        lines += ["", "## Why it failed", ""]
        lines += [f"- {r}" for r in card["reasons"]] or ["- (no reasons reported)"]
        lines += [
            "",
            "## Next step",
            "Label more sheets for the weak class(es) and retrain. The active-learning "
            "queue (`GET /api/active-learning/projects/{id}/review-queue`) already ranks "
            "the drawings the model is least sure about — start there.",
        ]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Render a model accuracy report from a golden.json")
    ap.add_argument("--golden", required=True, help="golden.json with gt + pred")
    ap.add_argument("--out", default=None, help="write the Markdown report here (else stdout)")
    ap.add_argument("--min-miou", type=float, default=None)
    ap.add_argument("--min-map", type=float, default=None)
    ap.add_argument("--max-error", type=float, default=None)
    args = ap.parse_args(argv)

    from ml.eval.harness import evaluate_dataset_file

    thresholds = {}
    if args.min_miou is not None:
        thresholds["min_miou"] = args.min_miou
    if args.min_map is not None:
        thresholds["min_map"] = args.min_map
    if args.max_error is not None:
        thresholds["max_measurement_error_pct"] = args.max_error

    report = evaluate_dataset_file(args.golden, thresholds or None)
    md = build_accuracy_report(report)
    if args.out:
        Path(args.out).write_text(md)
        print(f"[report] wrote accuracy report -> {args.out}")
    else:
        print(md)
    return 0 if report["gate_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
