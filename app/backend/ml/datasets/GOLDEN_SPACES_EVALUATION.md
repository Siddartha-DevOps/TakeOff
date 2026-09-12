# Golden evaluation specification — in-domain spaces v1

## Freeze and split contract

Target 30 untouched sheets (allowed range 20–40) from projects that occur in no train, validation, or test split. Include vector exports, rasterized PDFs, low-quality scans, text-heavy plans, multi-unit plans, crops, open plans, stairs, balconies, and storage. Revisions and pages from the same project may not cross splits. Golden labels and membership are immutable within a dataset version and must not be viewed for model/threshold tuning.

Before training, score the current checksum-pinned `resplan-yolov8m-seg-12ep-640-v1` checkpoint on this exact frozen set. That result is the in-domain baseline; the published ResPlan validation metrics are recorded context but are not a substitute because their domain differs.

## Required metrics

Report overall and per class, with support counts and 95% bootstrap confidence intervals where sample support permits:

- mask precision and recall at the frozen matching/confidence policy;
- mask mAP50 and mask mAP50-95;
- matched-instance intersection-over-union and Dice;
- room-count accuracy per sheet and per class: exact-match rate, absolute error, and percentage error;
- false positives, false negatives, and excluded/unmapped-region confusion;
- results sliced by vector/raster/scan, resolution, text density, multi-unit, open-plan, crop, and project.

Box metrics may be reported diagnostically but cannot replace mask metrics. Evaluation must retain prediction artifacts and a human false-positive/false-negative review log.

## Promotion gate

A candidate may be promoted only if all are true on the frozen in-domain golden set:

1. Mask mAP50 and mask mAP50-95 each improve by at least 0.03 over the current checkpoint's in-domain golden result.
2. Mask precision and recall are each no more than 0.02 below the in-domain baseline, and neither may trade a material regression for aggregate mAP.
3. Mean matched-instance IoU is at least 0.70 and Dice is at least 0.80.
4. Overall room-count exact accuracy is at least 0.90 and aggregate absolute percentage count error is at most 5%.
5. No class with adequate support regresses by more than 0.03 mAP50 or 0.03 recall; `balcony`, `stair`, and `storage` must have enough golden support to be judged rather than hidden in a macro average.
6. All mandatory difficulty slices are reported and no safety-critical slice has an unexplained material regression.
7. Dataset validation, rights review, checksum provenance, repeatability, and inference integration smoke checks pass.

The known ResPlan validation metrics (mask P 0.81441, R 0.78461, mAP50 0.80127, mAP50-95 0.68738) must remain in the model card, but direct promotion deltas are calculated against the baseline rerun on the same in-domain golden set.
