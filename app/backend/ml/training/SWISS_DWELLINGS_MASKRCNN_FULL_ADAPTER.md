# Swiss Dwellings Mask R-CNN full adapter

The full adapter is generated outside Git from the frozen Swiss Dwellings
training manifest. It creates one deterministic COCO uncompressed-RLE shard per
floor and hard-links (or verifies a copy of) the frozen rendered image. A small
SQLite ledger commits each floor only after image, annotation, instance-count,
and RLE round-trip verification.

## Guarantees

- Canonical metric room WKT is the instance source; connected components are
  never used.
- Polygon interiors are rasterized as holes and every RLE is decoded and
  compared with its source mask before the floor checkpoint commits.
- Existing outputs are verified byte-for-byte and are never silently replaced.
- Restarting resumes pending/failed floors and verifies every completed floor.
- Intentional negative floors have valid annotation shards with zero instances.
- The frozen building-level splits and duplicate-cluster leakage proof are
  checked again before the final manifest is published.
- Rejected instances and failed floors remain explicit evidence. A nonzero
  rejected count prevents treating the adapter as lossless training input.

## Command

Run from `app/backend`:

```powershell
python -m ml.datasets.adapt_swiss_rooms_maskrcnn_full `
  --source-manifest "E:\Takeoff_datasets\swiss_dwellings\processed\full-v1\manifests\swiss_dwellings_training_manifest_v1.json" `
  --output "E:\Takeoff_datasets\swiss_dwellings\processed\full-v1\mask-native\rooms-maskrcnn-coco-rle-full-v1" `
  --progress-every 100
```

The final `full-adapter-manifest.json` is content-addressed by the adjacent
`.sha256` file. An identical second pass must publish the same manifest bytes
before GPU preflight can be authorized. This adapter task does not authorize
training.

## Frozen full-adapter result

Both complete passes produced manifest SHA-256
`61966eb947ba0ffc2dbc094c33142246b2be3a9cdba085c9f0cb36e93279ce29`.
Pass 2 resumed the durable ledger, processed zero floors, and wrote zero
outputs. The frozen adapter contains 13,902 floors (11,337 train, 1,362
validation, 1,203 test), 495,835 authoritative and converted room instances,
7,669 hole-containing instances with 9,841 interior rings, four intentional
negative floors, and zero rejected instances. Missing or mismatched files,
building leakage, duplicate-relationship leakage, and duplicate-connected
cluster leakage are all zero.
