# ml/ — accuracy eval harness + retraining flywheel

Turn-key pipeline for measuring model accuracy on a fixed golden set and closing
the correction → retrain loop. Pure-Python and unit-tested; the heavy stages
(training, golden inference) run on a GPU box.

Two complementary eval paths:
- **`../eval_harness.py`** (existing) — scores the model against live user
  `CorrectionEvent`s. Real signal, but drifts with usage.
- **`ml/eval/`** (this package) — scores against a *fixed labeled golden set*.
  This is what gates a release (defensible, repeatable).

## Cold start — before any labels exist

The flywheel needs labels to turn, but a brand-new deployment has none. Two
bootstrap sources prime it (Phase 1 "AI MVP"):

- **`../ai/sam2_zero_shot.py`** — SAM2 zero-shot segments a plan into candidate
  room regions with **no trained model**. Rendered on the canvas, the user's
  accept/reject/label actions become the first `CorrectionEvent`s — feeding the
  export below.
- **`ml/datasets/bootstrap_public.py`** — remaps public floor-plan corpora
  (CubiCasa5K / RPLAN / Structured3D) onto the space-class list and writes a
  YOLOv8-seg dataset, so `train_yolov8_seg` can fine-tune a *first* space model
  before a single hand-labeled Takeoff sheet exists.

Both feed the same YOLO-seg dataset the correction export produces, so the loop
below runs identically once it's warm.

## The flywheel

```
SAM2 zero-shot ──► user accept/reject ──► CorrectionEvents ─┐
public datasets ──► ml/datasets/bootstrap_public ───────────┤
                                                            ▼
CorrectionEvents ──► ml/training/export_corrections ──► YOLO-seg dataset
                                                             │
                     training/train_yolov8_seg  ◄────────────┘
                             │ weights
                             ▼
        run weights on golden sheets ──► golden.json (gt + pred)
                             │
                     ml/eval/harness ──► {mIoU, mAP@0.5, measurement_error_pct}
                             │
                     promotion gate (mIoU≥0.70, mAP≥0.50, err≤5%)
                             │ pass
                     ml/registry/model_card + models.ModelVersion (ACTIVE)
```

`ml/training/retrain.py` orchestrates all of it.

## Metrics (`ml/eval/metrics.py`)
- **mIoU** — segmentation quality on rooms/spaces (greedy GT↔pred polygon match; a miss is 0).
- **mAP@0.5** — real all-point AP (COCO/VOC-2010), image-scoped matching, meaned over symbol classes.
- **measurement-error %** — aggregate MAPE of predicted vs ground-truth quantities (the "within ~5%" bar).

Targets come from `memory/TOGAL_PARITY_REAUDIT.md` §5 — chase ~70% time savings
and ≤5% quantity margin, **not** a marketing "98%".

## Commands

```bash
# 1. score a candidate against the golden set + gate (exit 1 if it fails)
python -m ml.eval.harness --dataset golden.json --report report.json

# 2. full flywheel on a training box
python -m ml.training.retrain \
    --name symbol_seg --version 2026.07.1 \
    --golden golden.json --base-dataset /data/base \
    --out-dir /artifacts --register
```

### Golden dataset format (`golden.json`)
A JSON list of per-sheet samples; see `ml/eval/harness.py` docstring. Each sample
carries ground-truth **and** predicted rooms (polygons), symbols (boxes+scores),
and quantities.

## Production ML pipeline — mission coverage

The full "eliminate mock, ship a real ML pipeline" mission maps to these modules
(reusing existing infra; new modules marked ★):

| # | Capability | Module |
|---|-----------|--------|
| 1 | Remove mock inference | `ai/inference/` (mock deleted; `ModelUnavailableError`) |
| 2 | YOLO training pipeline | `training/train_yolov8_seg.py` + `ml/training/retrain.py` (flywheel orchestrator) |
| 3 | ★ Dataset versioning | `ml/datasets/versioning.py` (content-addressed manifest + lineage) |
| 4 | ★ Annotation support | `ml/annotation/formats.py` (COCO / Label Studio / YOLO-seg converters) |
| 5 | Model evaluation | `ml/eval/` (mIoU, mAP@0.5, measurement-error, promotion gate) |
| 6 | Model registry | `ml/registry/model_card.py` + `models.ModelVersion` |
| 7 | Inference benchmarking | `ai/inference/benchmark.py` |
| 8 | GPU + CPU inference | `ai/inference/device.py` |
| 9 | Confidence scoring | `ai/inference/confidence.py` (thresholds, calibration, ECE) |
| 10 | ★ Active learning | `ml/active_learning/sampler.py` (uncertainty + disagreement sampling) |

New modules are pure NumPy/stdlib and unit-tested; heavy runtime (torch,
ultralytics, cv2) stays lazy so CI runs green on CPU.

**End-to-end flow:** annotate (`ml/annotation`) or bootstrap
(`ml/datasets/bootstrap_public`) → version the dataset (`ml/datasets/versioning`)
→ train (`training/train_yolov8_seg`) → evaluate + gate (`ml/eval`) → register
(`ml/registry`) → serve (`ai/inference`, device-aware + tiled) → surface uncertain
sheets (`ml/active_learning`) → user corrects → retrain (`ml/training/retrain`).

## Scope / what still needs a GPU + data
The code is complete and tested. To actually move the accuracy number you still
need: a labeled **golden plan set**, a **GPU** to fine-tune, and enough
**CorrectionEvents** to make the retrain dataset worthwhile. Until then the gate
runs but has nothing trained to promote — by design, it fails closed.
