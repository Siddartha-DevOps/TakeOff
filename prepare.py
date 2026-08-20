#!/usr/bin/env python
"""
prepare.py — TakeOff.ai frozen-eval measurement harness.

THIS FILE IS THE IMMUTABLE HARNESS. See program.md for the rules. It scores
whatever model currently sits at the inference-weights path against a frozen,
checksum-locked held-out set and prints exactly one scalar:

    val_map=<float in [0,1]>     a real segmentation mAP@0.5 on the frozen set
    val_map=-1                   HARD REJECT (see the failure table in program.md)

Design guarantees (why this scalar is trustworthy):
  - Eval-only. It never trains and never writes to data/eval_set/.
  - The frozen set is checksum-locked (data/eval_set/MANIFEST.sha256); if any
    eval image/label/yaml is added, removed, or edited, the run HARD-REJECTS.
    You cannot make a failing run pass by editing the eval set.
  - A broken model (zero predictions on images that all have ground truth) is a
    HARD REJECT (val_map=-1), NOT a silent mAP=0 that masquerades as a low score.

Usage:
    python prepare.py                     # score app/backend/models/best.pt
    MODEL_PATH=/abs/path/best.pt python prepare.py
    python prepare.py --weights /abs/path/best.pt
    python prepare.py --freeze            # SETUP ONLY: write MANIFEST.sha256 for
                                          # the current eval_set (run once, by a
                                          # human, when establishing the set)
"""
from __future__ import annotations

import argparse
import hashlib
import math
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
EVAL_DIR = REPO / "data" / "eval_set"
IMAGES_DIR = EVAL_DIR / "images"
LABELS_DIR = EVAL_DIR / "labels"
EVAL_YAML = EVAL_DIR / "data.yaml"
MANIFEST = EVAL_DIR / "MANIFEST.sha256"
DEFAULT_WEIGHTS = REPO / "app" / "backend" / "models" / "best.pt"

_IMG_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}
# Probe at a very low conf so "zero predictions" means the model genuinely
# emits nothing (broken) — not merely that it's under the default 0.25 gate.
_PROBE_CONF = 0.001


def _reject(msg: str) -> int:
    """Every failure path funnels here: one human line + the -1 contract line."""
    print(f"[prepare] REJECT: {msg}")
    print("val_map=-1")
    return 1


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _frozen_files() -> list[Path]:
    """Every file under the eval set except the manifest itself, in stable order."""
    return [p for p in sorted(EVAL_DIR.rglob("*"))
            if p.is_file() and p.name != MANIFEST.name]


def _compute_manifest() -> list[str]:
    return [f"{_sha256(p)}  {p.relative_to(EVAL_DIR).as_posix()}" for p in _frozen_files()]


def _freeze() -> int:
    if not IMAGES_DIR.is_dir():
        return _reject(f"cannot freeze: {IMAGES_DIR} does not exist")
    lines = _compute_manifest()
    MANIFEST.write_text("\n".join(lines) + "\n")
    print(f"[prepare] wrote {MANIFEST} ({len(lines)} files frozen)")
    return 0


def _verify_manifest() -> tuple[bool, str]:
    if not MANIFEST.is_file():
        return False, (f"no manifest at {MANIFEST} — run `python prepare.py --freeze` "
                       "once to establish the frozen eval set")
    expected = MANIFEST.read_text().strip().splitlines()
    actual = _compute_manifest()
    if expected != actual:
        return False, ("eval set does not match MANIFEST.sha256 — the frozen set was "
                       "modified (a file was added, removed, or edited). The eval set "
                       "is immutable; do not change it to make a run pass.")
    return True, ""


def _eval_images() -> list[Path]:
    return [p for p in sorted(IMAGES_DIR.rglob("*")) if p.suffix.lower() in _IMG_EXTS]


def _has_gt(img: Path) -> bool:
    lbl = LABELS_DIR / (img.stem + ".txt")
    return lbl.is_file() and lbl.read_text().strip() != ""


def _resolve_device() -> str:
    try:
        import torch
        return "0" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _count_predictions(weights: Path, images: list[Path], device: str) -> int:
    """Total predicted instances across `images` — the empty-model probe."""
    from ultralytics import YOLO
    model = YOLO(str(weights))
    total = 0
    for img in images:
        res = model.predict(source=str(img), device=device, conf=_PROBE_CONF, verbose=False)[0]
        boxes = getattr(res, "boxes", None)
        total += 0 if boxes is None else len(boxes)
    return total


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="TakeOff.ai frozen-eval harness (see program.md)")
    ap.add_argument("--freeze", action="store_true",
                    help="SETUP: write MANIFEST.sha256 for the current eval_set, then exit")
    ap.add_argument("--weights", default=os.environ.get("MODEL_PATH", str(DEFAULT_WEIGHTS)),
                    help="weights under test (default: app/backend/models/best.pt or $MODEL_PATH)")
    args = ap.parse_args(argv)

    if args.freeze:
        return _freeze()

    # 1. frozen eval set present + intact (checksum-locked)
    if not EVAL_YAML.is_file():
        return _reject(f"no frozen eval set at {EVAL_DIR} (need images/, labels/, data.yaml)")
    ok, why = _verify_manifest()
    if not ok:
        return _reject(why)

    # 2. model under test exists
    weights = Path(args.weights)
    if not weights.is_file():
        return _reject(f"no weights at {weights}")

    # 3. eval set must actually carry ground truth
    images = _eval_images()
    if not images:
        return _reject("eval set has no images")
    gt_images = [im for im in images if _has_gt(im)]
    if not gt_images:
        return _reject("no eval image has a non-empty ground-truth label")

    # 4. empty-prediction probe — a broken model is a HARD reject, not mAP=0
    device = _resolve_device()
    try:
        n_pred = _count_predictions(weights, gt_images, device)
    except Exception as exc:
        return _reject(f"inference failed on the eval set: {exc}")
    if n_pred == 0:
        return _reject(f"model produced ZERO predictions across {len(gt_images)} images that "
                       "all have ground-truth objects — treated as broken, not as a low score")

    # 5. score: seg mAP@0.5 via evaluate_model() (box metrics still computed, unused here)
    sys.path.insert(0, str(REPO / "app" / "training"))
    try:
        from train import evaluate_model
    except Exception as exc:
        return _reject(f"could not import evaluate_model from app/training/train.py: {exc}")
    try:
        metrics = evaluate_model(str(weights), str(EVAL_YAML), device=device)
    except Exception as exc:
        return _reject(f"evaluate_model raised: {exc}")

    val_map = metrics.get("mAP50_seg")
    if val_map is None:
        return _reject("evaluate_model returned no seg mAP (mAP50_seg) — is this a -seg model?")
    if not math.isfinite(val_map):
        return _reject(f"seg mAP is not finite ({val_map})")

    print(f"[prepare] weights={weights}  gt_images={len(gt_images)}  predictions={n_pred}  device={device}")
    print(f"val_map={val_map:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
