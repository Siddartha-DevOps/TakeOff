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
#   deps -> dataset (CubiCasa5K) -> preflight -> smoke(1 epoch) -> full train
#        -> golden eval + gate -> serving verify
#
# Override any of these via env, e.g.:  EPOCHS=50 IMGSZ=1024 bash scripts/train_spaces_gpu.sh
set -euo pipefail

TASK="${TASK:-spaces}"
DATA_ROOT="${DATA_ROOT:-data/cubicasa5k}"          # extracted CubiCasa5K tree
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

echo "==> [2/7] Acquiring CubiCasa5K (skipped if already extracted)"
if [ ! -d "$DATA_ROOT" ]; then
  python -c "from ml.datasets.acquire_cubicasa import download_cubicasa; download_cubicasa('cubicasa5k.zip')"
  mkdir -p "$DATA_ROOT"
  unzip -q cubicasa5k.zip -d "$DATA_ROOT"
fi

echo "==> [3/7] Converting to a versioned YOLO-seg dataset"
python -m ml.datasets.acquire_cubicasa --root "$DATA_ROOT" --out "$DATASET_OUT" --created-at "$CREATED_AT"

echo "==> [4/7] Preflight: can we train? (deps + dataset)"
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
