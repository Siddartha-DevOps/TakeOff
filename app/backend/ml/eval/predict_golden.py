"""
Predict the golden set (GPU box) — the missing bridge from trained weights to
the eval gate.

``build_golden.py`` builds the ground-truth side of ``golden.json``; the harness
needs the *prediction* side too. This module runs the trained model
(``ai.inference.InferenceEngine``) over a dataset's val images, converts each
sheet's detections to the harness prediction shape
(``build_golden.predictions_from_detections``), and — with ``--evaluate`` — runs
the whole gate in one command.

The image discovery and analysis→detections flattening are pure and unit-tested;
the model run is lazy (real weights on the GPU box), so this module imports on CI.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from ml.eval.build_golden import (
    attach_predictions,
    build_golden_gt,
    default_symbol_classes,
    predictions_from_detections,
    read_class_names,
)


def list_split_images(dataset_dir: str | Path, split: str = "val") -> list[tuple[str, Path]]:
    """Return ``(image_id, path)`` for every PNG in ``images/<split>/`` (sorted)."""
    images_dir = Path(dataset_dir) / "images" / split
    return [(p.stem, p) for p in sorted(images_dir.glob("*.png"))]


def analysis_to_detections(analysis) -> list[dict]:
    """Flatten a ``TakeoffAnalysis`` back into a single detection-dict list.

    Each of rooms/doors/windows/walls/balconies is already a list of detection
    dicts (``label``/``bbox``/``confidence``/``polygon``); concatenating them
    reconstructs the model's raw detections for the golden pred adapter. Accepts
    the dataclass or any object exposing those attributes.
    """
    dets: list = []
    for field in ("rooms", "doors", "windows", "walls", "balconies"):
        dets.extend(getattr(analysis, field, None) or [])
    return dets


def predict_split(engine, dataset_dir: str | Path, class_names, *, split: str = "val",
                  symbol_classes: Optional[set] = None) -> dict:
    """Run ``engine`` over the split's images -> ``{image_id: pred_dict}``.

    ``engine`` is any object with ``analyze(path, drawing_id)`` returning a
    ``TakeoffAnalysis`` (the real ``InferenceEngine``, or a stub in tests).
    """
    syms = symbol_classes if symbol_classes is not None else default_symbol_classes(class_names)
    preds: dict = {}
    for image_id, path in list_split_images(dataset_dir, split):
        analysis = engine.analyze(str(path), 0)
        dets = analysis_to_detections(analysis)
        preds[image_id] = predictions_from_detections(dets, symbol_classes=syms)
    return preds


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Predict the golden set with trained weights")
    ap.add_argument("--dataset", required=True, help="dataset dir (data.yaml + images/labels)")
    ap.add_argument("--split", default="val")
    ap.add_argument("--weights", default="models/best.pt", help="trained weights path")
    ap.add_argument("--device", default="auto")
    ap.add_argument("--out", default=None, help="write {image_id: pred} JSON here")
    ap.add_argument("--evaluate", action="store_true",
                    help="also build GT, attach preds, run the gate, and exit non-zero if it fails")
    args = ap.parse_args(argv)

    from ai.inference import InferenceEngine  # lazy — needs weights + torch (GPU box)

    class_names = read_class_names(Path(args.dataset) / "data.yaml")
    engine = InferenceEngine(model_path=args.weights, device=args.device)
    preds = predict_split(engine, args.dataset, class_names, split=args.split)

    if args.out:
        Path(args.out).write_text(json.dumps(preds, indent=2))
        print(f"[predict] wrote predictions for {len(preds)} sheets -> {args.out}")

    if args.evaluate:
        from ml.eval.harness import evaluate

        samples = attach_predictions(build_golden_gt(args.dataset, class_names, split=args.split), preds)
        report = evaluate(samples)
        print(json.dumps(report, indent=2))
        print(f"[predict] gate {'PASSED' if report['gate_passed'] else 'FAILED'}")
        return 0 if report["gate_passed"] else 1

    return 0 if preds else 1


if __name__ == "__main__":
    sys.exit(main())
