# GPU Training Runbook — spaces (room) model

Run on a **CUDA GPU box** (cloud instance, RunPod, Colab, or local). Not on CI or
Vercel — the app path stays CPU-light by design.

## Prerequisites
- An NVIDIA GPU + drivers (CUDA 12.x). A CPU-only box also works, just slowly —
  `device.py` resolves to CPU automatically.
- Python 3.11, `git`, `unzip`, ~15 GB free disk (CubiCasa5K is ~5 GB).
- The repo checked out; run everything from `app/backend/`.

## Do I need to provide data?
**No.** The run downloads **CubiCasa5K** (CC-BY-4.0, 5,000 annotated floor plans)
automatically — enough for a first spaces model. Add your own labeled drawings
later (via `ml/annotation/formats.py`) to specialize; the active-learning queue
(`/api/active-learning/...`) tells you which sheets to label first.

## One command
```bash
bash scripts/train_spaces_gpu.sh
```
Chains, with a readiness gate before each heavy stage:
`deps → CubiCasa5K → convert+version → preflight → smoke(1 epoch) → full train →
golden eval + gate → serving verify`. Override anything via env:
```bash
EPOCHS=50 IMGSZ=1024 DATASET_OUT=data/spaces_v2 bash scripts/train_spaces_gpu.sh
```

## Or step by step
```bash
pip install torch --index-url https://download.pytorch.org/whl/cu121
pip install -r requirements-ml.txt

# dataset → versioned YOLO-seg
python -c "from ml.datasets.acquire_cubicasa import download_cubicasa; download_cubicasa('cubicasa5k.zip')"
unzip -q cubicasa5k.zip -d data/cubicasa5k
python -m ml.datasets.acquire_cubicasa --root data/cubicasa5k --out data/spaces_v1 --created-at "$(date -u +%FT%TZ)"

python -m ml.preflight --data data/spaces_v1/data.yaml --require train   # gate
python -m ml.training.run_training --data data/spaces_v1/data.yaml --task spaces --smoke --no-promote
python -m ml.training.run_training --data data/spaces_v1/data.yaml --task spaces --epochs 100 --imgsz 1280

# evaluate the trained model against the gate (mIoU≥.70, mAP≥.50, err≤5%)
python -m ml.eval.predict_golden --dataset data/spaces_v1 --weights models/best.pt --evaluate
python -m ml.registry.release verify --task spaces
```

## Labeling your own plans (for accuracy on your sheet types)
Generate the Label Studio labeling interface from your class list, create a
project with it, label sheets (polygons for rooms, boxes for symbols), then
export — `ml/annotation/formats.label_studio_to_rings` + `acquire_cubicasa`-style
conversion turn the export into the trainer's format.

```python
from ml.datasets.bootstrap_public import SPACE_CLASSES
from ml.annotation.label_studio import build_labeling_config
print(build_labeling_config(SPACE_CLASSES, ["door", "window", "toilet", "sink"]))
# paste into Label Studio → Settings → Labeling Interface
```
Aim for ~150–400 labeled sheets to start; keep ~20–40 aside as the held-out
golden set (never trained on) for the accuracy report below.

## Accuracy report (the proof)
After `predict_golden --evaluate` produces the gate verdict, render a one-page
accuracy card to share or attach to a `ModelVersion`:

```bash
python -m ml.eval.build_golden --dataset data/spaces_v1 --out golden.json --predictions preds.json
python -m ml.eval.report --golden golden.json --out accuracy_report.md   # exit 1 if it fails the gate
```
It shows mIoU / mAP@0.5 / measurement-error vs thresholds, PASS/FAIL, sample
size, and — if it fails — which metrics missed and what to label next.

## Outputs
- `models/best.pt` — trained weights. `ai.inference` loads these on next server
  start; `analyze()` switches from `ModelUnavailableError` to real detections
  with **zero code change**.
- `data/spaces_v1/dataset_version.json` — the content-addressed dataset version.
- Gate verdict from `predict_golden --evaluate` (exit 1 if it fails the gate).

## Register + promote (with DB access, on the release box)
`predict_golden --evaluate` gives you the eval report; to persist a
`ModelVersion` and enforce the single-ACTIVE invariant, call
`ml.registry.release.release(db, name=..., version=..., task="spaces",
golden_path=..., weights_uri=..., stage_from="models/best.pt")`.

## Notes
- **Large sheets**: `imgsz` defaults to 1280; inference auto-tiles pages > 2000 px.
- **Symbol model** (doors/windows/MEP counts) is a separate run: `--task symbols`
  with a symbol dataset (weights → `ai/models/symbol_counts/yolov8-seg.pt`).
- **Colab**: same commands in a bash cell; set `CUDA_INDEX_URL` to match the
  runtime's CUDA version if needed.
