# ml/ — accuracy eval harness + retraining flywheel

Turn-key pipeline for measuring model accuracy on a fixed golden set and closing
the correction → retrain loop. Pure-Python and unit-tested; the heavy stages
(training, golden inference) run on a GPU box.

Two complementary eval paths:
- **`../eval_harness.py`** (existing) — scores the model against live user
  `CorrectionEvent`s. Real signal, but drifts with usage.
- **`ml/eval/`** (this package) — scores against a *fixed labeled golden set*.
  This is what gates a release (defensible, repeatable).

## The flywheel

```
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

## Scope / what still needs a GPU + data
The code is complete and tested. To actually move the accuracy number you still
need: a labeled **golden plan set**, a **GPU** to fine-tune, and enough
**CorrectionEvents** to make the retrain dataset worthwhile. Until then the gate
runs but has nothing trained to promote — by design, it fails closed.
