# AI Components Runbook — train / install every model

How to stand up all five AI components of TakeOff.ai. Run on a **CUDA GPU box**
(cloud VM, RunPod, Lambda, Vast, or Colab). Not on CI or Vercel — the app path
stays CPU-light by design (`device.py` falls back to CPU automatically, just
slowly).

> **The key fact: only 2 of the 5 are actually _trained_.** The other 3 are
> pretrained / zero-shot / rule-based — you **install and run** them.

| # | Component | Train it? | What you do |
|---|-----------|-----------|-------------|
| 1 | Space segmentation (YOLOv8-seg) | ✅ **Train** | label data → fine-tune → gate → promote |
| 2 | Symbol detection (YOLOv8-seg) | ✅ **Train** | label symbols → fine-tune → promote |
| 3 | SAM2 zero-shot | ❌ Install | download checkpoint, run as-is (label bootstrap) |
| 4 | CLIP ViT-B/32 | ❌ Install | install, bulk-encode sheets into pgvector |
| 5 | OCR (Tesseract) | ❌ Install | install the system binary — works immediately |

## Prerequisites (once)
- NVIDIA GPU + drivers (CUDA 12.x); 16 GB+ VRAM is comfortable.
- Python 3.11, `git`, `unzip`, ~15 GB free disk (CubiCasa5K is ~5 GB).
- Repo checked out; **run everything from `app/backend/`**.
```bash
pip install torch --index-url https://download.pytorch.org/whl/cu121   # match your CUDA
pip install -r requirements-ml.txt
python -m ml.preflight        # shows exactly what's present/missing
```

---

## 1. Space segmentation (YOLOv8-seg) — TRAIN
The core model: outlines and classifies rooms/spaces. Everything downstream
(measurement, quantities, BOQ, assemblies) consumes its output.

### Get data — public (zero effort) or your own (better accuracy)
**Public CubiCasa5K** (CC-BY-4.0, 5,000 plans) — fully automatic:
```bash
python -c "from ml.datasets.acquire_cubicasa import download_cubicasa; download_cubicasa('cubicasa5k.zip')"
unzip -q cubicasa5k.zip -d data/cubicasa5k
python -m ml.datasets.acquire_cubicasa --root data/cubicasa5k --out data/spaces_v1 --created-at "$(date -u +%FT%TZ)"
```
**Your own plans** (recommended for production accuracy) — label ~150–400 sheets,
keep ~20–40 aside as a held-out golden set:
```bash
python -c "from ml.datasets.bootstrap_public import SPACE_CLASSES; \
from ml.annotation.label_studio import build_labeling_config; print(build_labeling_config(SPACE_CLASSES))"
# → Label Studio → Settings → Labeling Interface → label (polygons) → export
# → convert the export with ml/annotation/formats.label_studio_to_rings
```

### Train (one command)
```bash
bash scripts/train_spaces_gpu.sh          # deps→data→preflight→smoke→train→eval→verify
# override: EPOCHS=50 IMGSZ=1024 bash scripts/train_spaces_gpu.sh
```
Or step by step:
```bash
python -m ml.preflight --data data/spaces_v1/data.yaml --require train
python -m ml.training.run_training --data data/spaces_v1/data.yaml --task spaces --smoke --no-promote
python -m ml.training.run_training --data data/spaces_v1/data.yaml --task spaces --epochs 100 --imgsz 1280
```
**Output:** `models/best.pt` → `ai.inference.InferenceEngine` loads it on next
server start. Cost ~$5–30, a few hours on one GPU.

### Prove accuracy (the gate)
```bash
python -m ml.eval.predict_golden --dataset data/spaces_v1 --weights models/best.pt --evaluate
python -m ml.eval.report --golden golden.json --out accuracy_report.md    # exit 1 if it fails
```
Gate: mIoU ≥ 0.70, mAP@0.5 ≥ 0.50, measurement-error ≤ 5%. The report shows
pass/fail per metric and, on failure, what to label next.

---

## 2. Symbol detection (YOLOv8-seg) — TRAIN
Detects + **counts** doors, windows, plumbing/electrical fixtures — the ~18
classes in `training/train_yolov8_seg.py:SYMBOL_CLASSES`.

- **Labels are boxes**, not polygons (RectangleLabels in Label Studio), or reuse
  CubiCasa's icon annotations.
```bash
python -m ml.training.run_training --data data/symbols_v1/data.yaml --task symbols --epochs 100 --imgsz 1280
```
**Output:** `ai/models/symbol_counts/yolov8-seg.pt` → `ai/detect_symbols.py` loads it.

> Vector PDFs count symbols geometrically with **no model**
> (`geometry/vector_symbol_match.py`); this trained model covers scanned/raster
> sheets.

---

## 3. SAM2 zero-shot — INSTALL (no training)
Proposes room regions with **no trained model** — used to *bootstrap* labels
faster (accept/relabel its proposals → those become training data).
```bash
pip install "git+https://github.com/facebookresearch/segment-anything-2.git"
mkdir -p ai/models/sam2
# place the checkpoint + config here (from the SAM2 repo / Hugging Face):
#   ai/models/sam2/sam2_hiera_large.pt
#   ai/models/sam2/sam2_hiera_l.yaml
```
Then:
```python
from ai.sam2_zero_shot import run_sam2_zero_shot
run_sam2_zero_shot("sheet.png")   # -> candidate room polygons; returns needs_weights until installed
```
No training step. `sam2_weights_available()` reports whether the checkpoint is in place.

---

## 4. CLIP ViT-B/32 — INSTALL + build the index (no training)
CLIP powers AI Search / pattern-count. Used **as-is** (pretrained); you install
it and encode your sheets once into pgvector.
```bash
pip install ftfy regex
pip install "git+https://github.com/openai/CLIP.git"     # provides `import clip`
```
Backfill embeddings for existing drawings (new uploads index automatically):
```python
from clip_embeddings import index_drawing_embeddings, clip_available
assert clip_available()
# per drawing (project_id, drawing_id, file_path, detection_json):
index_drawing_embeddings(db, project_id, drawing_id, file_path, detection_json)
```
After that, `POST /api/takeoff/projects/{id}/search/text | search/image | search/count`
return real results. *(Optional, much later: fine-tune CLIP on construction
imagery for better recall — not needed to start.)*

---

## 5. OCR (Tesseract) — INSTALL only (no training)
Rule-based title-block + scale-text reading. Works the moment the binary exists.
```bash
apt-get install -y tesseract-ocr     # Debian/Ubuntu; the system binary
pip install pytesseract              # already in requirements-ml.txt
```
`ai/title_block_ocr.py` and `ai/scale_detection.py` then work; both degrade
gracefully (numbered placeholder / no scale) if the binary is absent. Tesseract
can be fine-tuned for unusual fonts, but you almost never need to.

---

## Register + promote a trained model (release box, DB access)
`predict_golden --evaluate` produces the eval report; to persist a `ModelVersion`
and enforce the single-ACTIVE serving invariant:
```python
from ml.registry.release import release
release(db, name="spaces_seg", version="2026.07.1", task="spaces",
        golden_path="golden.json", weights_uri="s3://models/spaces/2026.07.1/best.pt",
        stage_from="models/best.pt")
```
Or just stage + verify on an inference box:
```bash
python -m ml.registry.release stage  --from runs/.../best.pt --task spaces
python -m ml.registry.release verify --task spaces      # exit 1 unless deps + weights present
```

## The improvement loop (after go-live)
Serve → users correct AI output → `ml/training/export_corrections` turns
corrections into new labels → retrain → re-gate → promote. The active-learning
queue (`GET /api/active-learning/projects/{id}/review-queue`) ranks which sheets
to label next.

## Summary — your real work
1. **Train space seg** — `bash scripts/train_spaces_gpu.sh` (biggest value).
2. **Train symbol detection** — same runner, `--task symbols`, once you have symbol labels.
3. **Install** SAM2 (label bootstrap), **CLIP** (search index), **Tesseract** (OCR).

Everything above is already coded and tested — you're running it, not building it.
