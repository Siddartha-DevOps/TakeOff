# `models/` — trained weights drop point (the weights contract)

This directory is where trained model weights live at runtime. It is the
**authoritative path** the server loads from:

- `server.py` → `AI_MODEL_PATH = os.environ.get("AI_MODEL_PATH", "models/best.pt")`
- `ai/inference/engine.py` → `InferenceEngine(model_path=AI_MODEL_PATH)`

## Contract

| File | Task | Loaded by |
|------|------|-----------|
| `models/best.pt` | space segmentation (rooms) | `ai.inference.InferenceEngine` (task `spaces`) |
| `ai/models/symbol_counts/yolov8-seg.pt` | symbol detection (doors/windows/MEP) | `ai/detect_symbols.py` |

Weights are **not committed to git** (`.gitkeep` keeps the dir; `*.pt` is
ignored). They are produced by the training pipeline
(`training/train_yolov8_seg.py` → `ml/training/retrain.py`) and delivered here by
one of:

1. **Private Hugging Face provisioning** in production. Set the variables below;
   startup verifies the pinned SHA-256 and atomically installs the artifact.
   An already-verified volume copy is reused without network access.
   ```bash
   AI_MODEL_PATH=/models/best.pt
   AI_MODEL_REPO_ID=Siddartha96/takeoff-spaces-yolov8m-seg
   AI_MODEL_FILENAME=best.pt
   AI_MODEL_SHA256=2cc2cfffaa294f9915a2fddab9812f06b10450e8149e75d5d3361f5b792c9acd
   HF_TOKEN=<a-token-with-read-access>
   ```
2. **Manual copy** after a training run: `cp runs/.../best.pt models/best.pt`.

## Behavior without weights (by design — no mock)

When `models/best.pt` is absent, `InferenceEngine.available` is `False` and
`analyze()` raises `ModelUnavailableError`. The engine never fabricates
detections. Vector-PDF takeoff (`/autodetect`) still returns real results.

Run `python -m ml.preflight` to see exactly what is present/missing before
training or serving.
