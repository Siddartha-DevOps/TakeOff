# TakeOff.ai model registry

`app/backend/ml/registry/model_registry.json` is the reproducibility record for
model artifacts stored outside Git. `ml.registry.metadata` validates and writes
the registry and verifies artifact SHA-256 values. The existing database
`ModelVersion` table remains the operational promotion index; this file-backed
record adds dataset, taxonomy, architecture, and artifact evidence without
duplicating weights.

Statuses are `EXPERIMENTAL`, `CANDIDATE`, `PRODUCTION`, and `RETIRED`. A model
cannot be recorded as `PRODUCTION` without an evaluation version, and the
registry enforces at most one production version per model line.

## Current room artifact

- ID/version: `takeoff-spaces-resplan` /
  `resplan-yolov8m-seg-12ep-640-v1`.
- Architecture: YOLOv8m-seg, 640px, seven ordered room classes.
- Dataset: ResPlan-derived `spaces_v1@097a39c19c57a208`.
- Training evidence: 12 epochs, not the one-epoch smoke configuration.
- Artifact: `app/backend/models/best.pt`, 54,826,133 bytes.
- SHA-256:
  `2cc2cfffaa294f9915a2fddab9812f06b10450e8149e75d5d3361f5b792c9acd`.
- Serving pin: private HF repository
  `Siddartha96/takeoff-spaces-yolov8m-seg`, cached revision
  `e6eed685f498e8a5af8ee16481840f115de287fd`.
- Registry status: **CANDIDATE**.

The artifact is pinned by serving, but no independent customer-domain golden
report or formal promotion record exists. Serving configuration is not evidence
of production accuracy, so `best.pt` is intentionally not marked PRODUCTION.

## Prediction contract

`ml.prediction.Prediction` is the common provenance-preserving contract for
rooms, walls, doors, windows, columns, fixtures, and future MEP models. It
requires prediction/model/dataset IDs, drawing/page IDs, class, confidence,
timestamp, and validated `BOUNDING_BOX`, `POLYGON`, `LINESTRING`, or `POINT`
geometry. Product inference integration belongs to Task 7; this task defines
and tests the stable boundary without rewriting the existing detection tables.
