#!/usr/bin/env bash
#
# End-to-end GPU training run for the TakeOff.ai spaces (room) model.
# Run this on a CUDA box (or Colab/RunPod bash) — NOT in CI or on Vercel.
#
#   bash scripts/train_spaces_gpu.sh
#
# It chains the whole pipeline with a readiness gate before each heavy stage, so
# it fails loudly and early rather than halfway through a multi-hour train:
#
#   deps -> dataset (ResPlan) -> data audit -> preflight -> smoke -> full train
#        -> golden eval + gate -> serving verify
#
# Override any of these via env, e.g.:  EPOCHS=50 IMGSZ=1024 bash scripts/train_spaces_gpu.sh
set -euo pipefail

TASK="${TASK:-spaces}"
DATA_SOURCE="${DATA_SOURCE:-data/resplan/source}"   # pinned official ResPlan source
DATASET_OUT="${DATASET_OUT:-data/spaces_v1}"       # converted YOLO-seg dataset
EPOCHS="${EPOCHS:-100}"
IMGSZ="${IMGSZ:-1280}"
WEIGHTS="${WEIGHTS:-models/best.pt}"
CUDA_INDEX_URL="${CUDA_INDEX_URL:-https://download.pytorch.org/whl/cu121}"

# Run from the backend root (this script lives in backend/scripts/).
cd "$(dirname "$0")/.."
CREATED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

echo "==> [1/7] Installing ML dependencies"
pip install --quiet torch --index-url "$CUDA_INDEX_URL"
pip install --quiet -r requirements-ml.txt

echo "==> [2/7] Acquiring pinned official ResPlan source (skips existing verified files)"

echo "==> [3/7] Converting to a versioned YOLO-seg dataset"
python -m ml.datasets.acquire_resplan --source "$DATA_SOURCE" --out "$DATASET_OUT" \
  --created-at "$CREATED_AT"

echo "==> [4/7] Preflight: can we train? (deps + dataset)"
python -m ml.datasets.validate_spaces --data "$DATASET_OUT/data.yaml" --require-groups \
  --manifest "$DATASET_OUT/spaces-v1.manifest.json"
python -m ml.preflight --data "$DATASET_OUT/data.yaml" --require train

echo "==> [5/7] Smoke run (1 epoch, no promotion) — verifies the pipeline"
python -m ml.training.run_training --data "$DATASET_OUT/data.yaml" --task "$TASK" --smoke --no-promote

echo "==> [6/7] Full training (epochs=$EPOCHS imgsz=$IMGSZ) -> $WEIGHTS"
python -m ml.training.run_training --data "$DATASET_OUT/data.yaml" --task "$TASK" \
  --epochs "$EPOCHS" --imgsz "$IMGSZ"

echo "==> [7/7] Golden eval + promotion gate, then serving verify"
python -m ml.eval.predict_golden --dataset "$DATASET_OUT" --weights "$WEIGHTS" --evaluate
python -m ml.registry.release verify --task "$TASK" --weights "$WEIGHTS"

echo "==> Done. Trained weights at $WEIGHTS — ai.inference will load them on next server start."
echo "    (To register + promote a ModelVersion with DB access, use ml.registry.release.release.)"
