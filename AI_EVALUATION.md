# TakeOff.ai AI evaluation status

## Current status: NOT EVALUATED

The existing ResPlan YOLOv8m-seg checkpoint has embedded training-validation
metrics, but it has **not** been run against a rights-cleared, independent,
customer-domain golden benchmark. It is therefore not production-ready by
evaluation evidence.

**BLOCKED — NO VALID TEST SET** for final TakeOff customer-domain evaluation.
The ResPlan test split is useful source-domain evidence, but it cannot establish
accuracy on contractor drawings. Swiss Dwellings is geometry pretraining data,
not the final customer-domain golden set.

## Evidence that does exist

The checkpoint embeds these source-domain validation values:

| Metric | Box | Mask |
|---|---:|---:|
| Precision | 0.80940 | 0.81441 |
| Recall | 0.78199 | 0.78461 |
| mAP50 | 0.79503 | 0.80127 |
| mAP50-95 | 0.73603 | 0.68738 |

These numbers must always be labeled training/source-domain validation. There
is no recorded independent IoU, Dice, room-count, area-error, or perimeter-error
result for `best.pt`.

## Evaluation runner

`ml.eval.runner` emits per-image and aggregate precision, recall, F1, matched
IoU, Dice, room-count accuracy/absolute error, area error, perimeter error, and
per-class results. It consumes fixed ground truth plus model predictions and
emits `NOT_EVALUATED` for an empty benchmark rather than fabricating metrics.

`app/backend/tests/fixtures/ai_golden/manifest.json` is the repository-controlled
benchmark index. It contains no copyrighted/private drawings. Future sample
records must reference externally stored, rights-cleared assets and cover:
simple and complex plans, scans, vector-origin plans, multiple scales, and
multiple drawing styles.

## Status meanings

- **NOT EVALUATED**: no valid independent report exists.
- **EVALUATED**: a frozen model was scored on a frozen, licensed benchmark.
- **PRODUCTION READY**: an evaluated model passed the documented gate, its
  checksum and dataset/evaluation versions are registered, and it was formally
  promoted. Neither a deployed endpoint nor a training metric alone qualifies.
