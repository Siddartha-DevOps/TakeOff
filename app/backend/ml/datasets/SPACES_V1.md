# spaces-v1 dataset contract

`spaces-v1` is the first trainable TakeOff model. GPU training must not begin
until this dataset passes the strict validator.

## Required layout

```text
spaces_v1/
  data.yaml
  groups.json
  images/train/*.png
  images/val/*.png
  images/test/*.png        # strongly recommended for final evaluation
  labels/train/*.txt
  labels/val/*.txt
  labels/test/*.txt
```

Each label is YOLO segmentation format: one class id followed by at least three
normalized `x y` polygon points. Every image must have a matching label file.
An intentionally negative sheet uses an empty label file.

`groups.json` maps each sample stem (or image-relative path) to its source
project. All sheets and revisions from one construction project must stay in a
single split:

```json
{
  "project_101_sheet_A1": "project_101",
  "project_101_sheet_A2": "project_101",
  "project_205_sheet_A1": "project_205"
}
```

Keep the class order in `data.yaml` identical to the inference class contract.
TakeOff's current public bootstrap uses seven room types. A one-class model can
instead be enforced by passing `--expected-class space`; do not mix the two
taxonomies within one model version.

## Validate and freeze the dataset

Run from `app/backend`:

```bash
python -m ml.datasets.validate_spaces \
  --data data/spaces_v1/data.yaml \
  --require-groups \
  --manifest data/spaces_v1/spaces-v1.manifest.json
```

The command exits non-zero for malformed polygons, missing image/label pairs,
unknown classes, identical images across splits, or a project appearing in more
than one split. The manifest hashes every image and label so a training run can
be reproduced exactly.

After this passes, run the one-epoch smoke training command. Do not use the test
split for training decisions; it is the final unbiased accuracy check.
