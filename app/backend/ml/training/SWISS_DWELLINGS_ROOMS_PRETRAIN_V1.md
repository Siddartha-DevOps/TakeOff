# Swiss Dwellings room pretraining v1

## Frozen evidence and scope

This plan is room/space segmentation only. It references the immutable Swiss
Dwellings training manifest SHA-256
`6375b709932223b328de146282549807c4e2555526d4a2654ff216c68b377c4b` and
preserves its 11,337 / 1,362 / 1,203 train/validation/test floor assignments.
Floors 5593, 5639, and 5640 remain excluded source-data exceptions. The test
split is not loaded during optimization, early stopping, or model selection.

## Taxonomy decision

The first Swiss pretraining run uses all fourteen approved `TRAIN` semantics in
mask-ID order: bedroom, bathroom, kitchen, living, living-dining, corridor,
storage, balcony, office, utility, stairs, entry/lobby, generic room, and shaft.
The JSON configuration records every source-to-canonical mapping. Every Swiss
`REVIEW`, `MAP_TO_OTHER`, or `IGNORE_FOR_CURRENT_MODEL` semantic remains in
metric provenance and is absent from current labels; none is silently merged.

The deployed ResPlan checkpoint has seven ordered classes: living, bedroom,
bathroom, kitchen, balcony, stair, and storage. These correspond to seven Swiss
semantics, with `stair` normalized to `stairs`. Living-dining, corridor, office,
utility, entry/lobby, generic room, and shaft are new. Because both the order and
class count change, the YOLO head cannot be reused as-is. Compatible
YOLOv8m-seg backbone/neck parameters transfer from the checksum-pinned ResPlan
checkpoint; the fourteen-class prediction head is initialized for this run.

## Training decision

The proven repository family remains Ultralytics YOLOv8m-seg. The planned run
uses 1280-pixel input, batch 4, 100 epochs, AdamW at initial learning rate 0.001,
cosine decay to 1%, 3 warmup epochs, AMP, checkpointing every 5 epochs, and
validation-loss early stopping with patience 20. Seed 42 and deterministic mode
are mandatory. Plan augmentation is monochrome-safe: no HSV, perspective,
shear, mosaic, mixup, or copy/paste; only 2-degree scan skew, 2% translation,
10% scale, and horizontal/vertical flips.

Train instance counts range from 92 entry/lobby instances to 81,604 shafts.
The approved policy is deterministic square-root inverse-frequency floor
sampling capped to 0.5x–3x, with source-row multiplicity contributing no extra
weight and negative-only floors capped at 10% of a batch. Raw inverse-frequency
weighting is prohibited. Per-class metrics and support remain mandatory.

## Blocking data-contract gap

The frozen manifest references `room_semantic.png` labels (IDs 1–14). The
existing YOLOv8m-seg runner consumes instance polygon TXT labels (IDs 0–13).
Although immutable `room_instance.png` and metric `supervision.json.gz` files
exist beside each render, a deterministic, separately versioned
manifest-to-YOLO adapter has not yet been materialized and frozen. Starting the
trainer now would either fail or use an unverified parallel label source.

Therefore this configuration parses and its source data passes read-only sanity
checks, but the training run is **not authorized or start-ready**. The next gate
is to build and validate that adapter without modifying the frozen render
manifest, then rerun this preflight and issue the final `--no-promote` command.

## Evaluation and domain limitation

Capture overall and per-class mask precision, recall, matched-instance IoU,
mask mAP50, mask mAP50-95, confusion matrix, and validation box,
segmentation, classification, and DFL losses. Compare the ResPlan baseline only
on the seven shared semantics and on the same frozen Swiss validation split.
Swiss validation measures geometry-pretraining performance, not production
accuracy on contractor documents. Rights-cleared real AEC/customer drawings
and an untouched customer-domain golden set remain required before promotion.

Recommended GPU capacity is one 24 GB A10G/L4-class device for batch 4 at 1280;
a 16 GB T4-class device should use batch 2 after a memory smoke test. This is a
capacity estimate from the repository's existing A10G/T4 configurations, not a
measured profile of this unstarted run.
