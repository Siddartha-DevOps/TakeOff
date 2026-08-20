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

1. **Volume mount / init-container** in production (`ai/inference/Dockerfile`
   mounts `/models`), pulling the ACTIVE `ModelVersion`'s artifact.
2. **Manual copy** after a training run: `cp runs/.../best.pt models/best.pt`.

## Behavior without weights (by design — no mock)

When `models/best.pt` is absent, `InferenceEngine.available` is `False` and
`analyze()` raises `ModelUnavailableError`. The engine never fabricates
detections. Vector-PDF takeoff (`/autodetect`) still returns real results.

Run `python -m ml.preflight` to see exactly what is present/missing before
training or serving.
