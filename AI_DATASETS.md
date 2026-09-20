# TakeOff.ai dataset registry

The machine-readable registry is
`app/backend/ml/datasets/dataset_registry.json`. Dataset bytes remain outside
Git; the registry records source, license/provenance, ordered classes, counts,
split policy, creation time, and a SHA-256 of the authoritative manifest.

## Registered dataset

`resplan-spaces-v1@097a39c19c57a208` is the only dataset currently tied to a
trained TakeOff checkpoint:

- Source: official ResPlan archive/splits pinned to upstream commit
  `e2b78fe069aee1ab1e1828a612743f308e3c32a7`.
- License recorded by the local source metadata: CC BY 4.0.
- Classes: living, bedroom, bathroom, kitchen, balcony, stair, storage.
- Images: 16,296 (13,053 train / 1,622 validation / 1,621 test).
- Annotations: 133,905 YOLO instance polygons.
- Split rule: source-drawing/project identity must remain isolated. Pages may
  never be randomly split across train, validation, and test.

The local `spaces_v1` bytes and generated Swiss Dwellings artifacts are ignored
training data, not repository source files. CubiCasa5K remains research-only and
commercial-blocked under the evidence currently recorded in
`AI_TRAINING_MASTER_STATUS.md`.

## Validation

`ml.datasets.validator.validate_dataset_index` validates an external index and
writes a machine-readable report. It checks missing/corrupt images, missing and
empty annotations, invalid YOLO polygons/boxes, unknown classes, duplicate
images/hashes, annotation/image mismatch, project leakage, and cross-split
duplicates. `ml.datasets.validate_spaces` remains the optimized validator for
the existing spaces-v1 YOLO layout.

An external index has this shape:

```json
{
  "root": "E:/datasets/rooms-v2",
  "classes": ["bedroom"],
  "samples": [{
    "sample_id": "project-a/A-101",
    "project_id": "project-a",
    "split": "test",
    "image": "images/test/A-101.png",
    "annotation": "labels/test/A-101.txt",
    "annotation_format": "yolo_segmentation"
  }]
}
```

Empty annotations are warnings because intentional negative sheets are valid,
but their intent must be documented by the dataset owner.
