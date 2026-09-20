# TakeOff.ai AI Training Master Status

**Audit date:** 2026-09-01
**Scope:** Current repository, local ignored data/model artifacts, checkpoint metadata, production configuration, public GitHub Actions metadata, production health, and anonymous Hugging Face status.
**Rule used:** Code paths and plans are not evidence of a completed run. A run is counted only when a real checkpoint or run output exists.

## Executive verdict

The repository has one genuine trained model: a 12-epoch YOLOv8m instance-segmentation checkpoint pretrained on the ResPlan-derived `spaces_v1` dataset. It is not a one-epoch smoke model. Its embedded validation metrics are credible training-run evidence, and the local checkpoint SHA-256 exactly matches the checksum pinned by the Hugging Face Space source.

The model is still **PARTIAL**, not production-complete. It has only synthetic/vector-derived ResPlan pretraining, no representative customer-drawing fine-tune, no independent held-out golden evaluation, no IoU/Dice or measurement-error report, and no evidence that it passed the repository's `ModelVersion` promotion gate. No trained wall, door/window, fixture, or MEP checkpoint was found.

## Verified production artifact

| Field | Verified value | Evidence / limitation |
|---|---|---|
| Production AI backend | `huggingface_space` | `render.yaml` points to `Siddartha96/takeoff-spaces-inference`; production `/api/health` returned HTTP 200 with `ai_engine=loaded`, `ai_backend=huggingface_space`. This proves adapter configuration, not a successful inference request. |
| Space endpoint | `Siddartha96/takeoff-spaces-inference`, API `/predict_spaces` | `render.yaml`, `server.py`, `ai/inference/remote_space.py`. |
| Model repository | `Siddartha96/takeoff-spaces-yolov8m-seg` | Hard-pinned in `app/backend/ai/space/app.py`. The repository is private; anonymous HF API returned 401. |
| Checkpoint | `best.pt` | Hard-pinned in Space source and local model contract. |
| Model version label | `resplan-yolov8m-seg-12ep-640-v1` | `app/backend/ai/space/app.py`. |
| Model architecture | YOLOv8m-seg, instance segmentation | Checkpoint pickle identifies `SegmentationModel`, `yolov8m-seg.yaml`, and seven trained class names. |
| Training parameters | 12 epochs, image size 640, batch 8 | Embedded checkpoint `train_args`. Smoke configuration is 1 epoch, image size 320, batch 2, so this is not a smoke checkpoint. |
| Expected SHA-256 | `2cc2cfffaa294f9915a2fddab9812f06b10450e8149e75d5d3361f5b792c9acd` | Space source and model provisioning contract. |
| Repository `best.pt` SHA-256 | `2cc2cfffaa294f9915a2fddab9812f06b10450e8149e75d5d3361f5b792c9acd` | Direct SHA-256 of the 54,826,133-byte local file. It is byte-identical by checksum to the artifact pinned by Space source. |
| Cached HF model revision | `e6eed685f498e8a5af8ee16481840f115de287fd` | First field in Hugging Face download metadata for local `best.pt`; artifact etag/checksum is the expected SHA-256. |
| Live Space revision | **Not independently verified** | HF model/Space APIs returned 401 anonymously and the private `hf.space` endpoint returned 404 anonymously. No HF credential is available in this audit environment. |
| Deployment provenance | **Not verified as successful** | The only public GitHub Actions run for `deploy-huggingface-space.yml`, run `33191545745` at source commit `10f6d2cd268a7b97848f1c506246ce306040c868`, failed in `Upload the reviewed inference bundle`. A manual/private deployment may exist, but the repository does not prove it. |

### Promotion classification

The checkpoint is **pinned in the production serving configuration**, but it is **not proven production-promoted** through TakeOff's formal evaluation/registry process. No committed or local golden dataset, evaluation report, model card, benchmark result, or `ModelVersion` promotion record was found. The checkpoint should be treated as a pinned ResPlan-pretrained serving candidate until an authenticated Space inspection and formal golden-gate run prove otherwise.

## Dataset inventory

| Dataset | Purpose | Classes | Size in current workspace | Annotation format | Prepared | Trained | Best checkpoint | Metrics | Production usage | Next action |
|---|---|---|---:|---|---|---|---|---|---|---|
| `spaces_v1` / ResPlan dataset version `097a39c19c57a208` | Room/space pretraining | living, bedroom, bathroom, kitchen, balcony, stair, storage | 16,296 images; 133,905 polygons; train 13,053 / val 1,622 / test 1,621 | YOLO instance-segmentation polygons, normalized points; project/layout group split metadata | **Yes.** Content-addressed dataset, source hashes, group splits, and manifest exist. | **Yes, 12 epochs** | `models/best.pt` | Embedded box/mask metrics below | Checkpoint is the artifact pinned by current Space source | Build rights-cleared in-domain fine-tune and golden sets; then fine-tune and formally promote. |
| `spaces_v1_smoke` | Pipeline smoke fixture derived from ResPlan | Same seven classes | 74 images; train 25 / val 24 / test 25 | YOLO segmentation polygons | Yes, smoke-only | No persistent smoke checkpoint found | None | None | None | Keep only for pipeline smoke tests. |
| CubiCasa5K | Research-only room/layout/opening/object source | 32 space labels; walls; 8 door subtypes; 3 window subtypes; stairs/railings/columns; 66 fixed-furniture classes | Official 5,000-plan archive present externally; 6,171 original pages + 6,171 scaled pages; 5,000 SVGs | SVG/XML polygons, paths, nested groups, and transforms | **Audited, not converted.** Exact official archive verified; raw copy stays outside Git. Not production-prepared because of license, duplicates, mapping, and converter gaps. | No | None | None | None | **Do not use for commercial training.** Obtain a commercial license or exclude it; preserve as research-only. |
| RPLAN / HouseGAN sample | Legacy room bootstrap reference | Legacy 27-class plan proposes 9 rooms plus objects | 0 samples present | Referenced `.npy`/HDF5 source; no prepared manifest | Reference/downloader only | No | None | None | None | Prefer the already prepared ResPlan source unless a reviewed RPLAN need is established. |
| CVC-FP | Legacy room segmentation reference | Not concretely mapped in a present manifest | 0 samples present | Not prepared | No | No | None | None | None | License and class-map review before acquisition. |
| Structured3D | Legacy synthetic layout reference | Not concretely mapped in a present manifest | 0 samples present | Not prepared | No | No | None | None | None | Use only to fill measured domain gaps after in-domain evaluation. |
| SESYD / CubiCasa icons | Symbols, fixtures, doors/windows | 18-class object contract: door, window, sink, toilet, bathtub, shower, washer, dryer, refrigerator, stove, dishwasher, water heater, outlet, switch, light, HVAC, stairs, elevator | 0 images/labels present | Pascal VOC XML source converter -> YOLO detection boxes | Converter/scaffold only; generated dataset absent and converter output still needs train/val split | No | None | None | None | Acquire rights-cleared source, normalize taxonomy, split by source drawing, validate, then train. |
| `symbols_v1` | Alternate raster symbol segmentation contract | 18 typed classes: 5 door, 5 window, 4 plumbing, 4 electrical | Dataset absent | YOLO segmentation polygons | No | No | None | None | Stable target path exists but no weights | Decide detection-vs-segmentation contract, then prepare one canonical dataset rather than parallel taxonomies. |
| Wall patches | Interior/exterior/non-wall classifier prototype | exterior wall, interior wall, non-wall | 0 patches present | ImageFolder classification patches | No | No | None | None | No `wall_classifier_v1.pt` found | Replace/augment patch classification with estimator-grade wall masks/centerlines and thickness labels. |
| Customer corrections / active learning | In-domain fine-tuning source | Uses application annotation labels | No frozen training version found | Existing export code can convert accepted corrections | Pipeline code only | No | None | None | Not used for current checkpoint | Export, de-identify, review rights, freeze dataset version, and create held-out project-level split. |

### Dataset validation findings

- `spaces_v1` remains the only full dataset that is prepared and license-compatible with the current commercial pretraining workflow. Its manifest reports dataset ID `1de1c507874f9e66`, seven classes, the exact split counts above, and polygon counts of 107,307 train / 13,310 validation / 13,288 test.
- Its source metadata pins ResPlan commit `e2b78fe069aee1ab1e1828a612743f308e3c32a7`, archive/split hashes, and CC BY 4.0 attribution.
- The supplied augmented split was excluded and 21 semantic-layout collisions were removed, according to the dataset card.
- It is vector-derived pretraining data, not representative validation for scanned or real AEC construction documents.
- CubiCasa5K is now physically present and audited outside Git, but it is not a production-eligible or converted dataset. All other named datasets remain references, acquisition/conversion code, or test scaffolds without present approved samples.

## Training runs and checkpoints

| Component | Completed run evidence | Classification | Checkpoint evidence |
|---|---|---|---|
| Room/space segmentation | Real checkpoint with 12 epochs of `train_results`, 12-epoch train args, seven class names, and final validation metrics | **Intermediate/full-budget ResPlan pretraining run. Not smoke; not final production training.** | `app/backend/models/best.pt`, 54,826,133 bytes, ignored by Git, plus matching HF download metadata |
| Kaggle room notebook | Notebook defines one-epoch smoke and optional 12-epoch full run | **Not executed in repository:** 0 executed cells, 0 output cells | None attributable to notebook execution |
| Colab room notebook | Notebook defines smoke/full/eval/download flow | **Not executed in repository:** 0 executed cells, 0 output cells | None attributable to notebook execution |
| Wall classifier/vectorization | Training code only | Not run | No `.pt`, `.pth`, or ONNX artifact |
| Door/window model | Training code/taxonomies only | Not run | No object/symbol checkpoint |
| Fixture/symbol/MEP model | Training code/taxonomies only | Not run | No `ai/models/symbol_counts/yolov8-seg.pt` or object checkpoint |
| SAM2 | Zero-shot dependency only, not a TakeOff-trained model | Not installed in workspace | No SAM2 checkpoint |
| CLIP | Pretrained `openai/clip-vit-base-patch32`, loaded dynamically by Space | No TakeOff fine-tuning run | No local TakeOff checkpoint; production source references upstream pretrained model |
| OCR | Tesseract system model/rules, not TakeOff-trained | No custom training | No custom OCR checkpoint |

### Existing checkpoint inventory

Only one model binary was found outside ignored dependency/cache trees:

- `app/backend/models/best.pt` — YOLOv8m-seg spaces model, 54,826,133 bytes, SHA-256 `2cc2cfffaa294f9915a2fddab9812f06b10450e8149e75d5d3361f5b792c9acd`.

No `last.pt`, ONNX export, wall classifier, object detector, symbol segmentation weights, SAM2 weights, or custom CLIP checkpoint was found.

## Metrics recovered from `best.pt`

These values are embedded Ultralytics validation metrics from the training checkpoint. They are **not** an independent customer-domain golden evaluation.

| Metric | Box | Mask/segmentation |
|---|---:|---:|
| Precision | 0.80940 | 0.81441 |
| Recall | 0.78199 | 0.78461 |
| mAP50 | 0.79503 | 0.80127 |
| mAP50-95 | 0.73603 | 0.68738 |

| Validation loss | Value |
|---|---:|
| Box loss | 0.18904 |
| Segmentation loss | 0.21379 |
| Classification loss | 0.23393 |
| DFL loss | 0.83249 |

- **Segmentation IoU:** not found.
- **Dice:** not found.
- **Takeoff measurement error:** not found.
- **Per-class metrics/confusion matrix:** not found as a durable artifact.
- **Independent benchmark/golden report:** not found.

The repository contains evaluation and promotion code with default golden gates of mIoU >= 0.70, symbol mAP@0.5 >= 0.50, and aggregate measurement error <= 5%, but no evidence that this checkpoint was run through or passed that gate.

## Model promotion process: code versus evidence

The intended process is sound in code:

1. Freeze a content-addressed dataset version.
2. Train and produce `best.pt`.
3. Generate predictions against a held-out golden dataset.
4. Run `ml.eval.harness` / `ml.eval.report`.
5. Register a `ModelVersion` candidate with dataset and weight provenance.
6. Promote only a passing candidate to the single `ACTIVE` version.
7. Stage the approved weight at the inference contract path or pinned object/HF URI.

For the current checkpoint, steps 1-2 and checksum pinning are evidenced. Steps 3-6 are not evidenced. A hardcoded Space model version and SHA are not substitutes for the formal promotion record.

## Completion estimate

The percentages use five evidence milestones per supervised model family: prepared/versioned dataset, completed run, durable checkpoint, independent in-domain evaluation, formal production promotion.

| Area | Completion | Basis |
|---|---:|---|
| Dataset preparation across room, wall, door/window, symbols, MEP | 20% | Only room pretraining data is prepared/versioned (1 of 5 families). |
| Room/space model training | 60% | Dataset, run, and checkpoint exist; in-domain fine-tune/golden evaluation and formal promotion do not. |
| Wall model training | 0% | No prepared data, completed run, or checkpoint. |
| Door/window training | 0% | No prepared data, completed run, or checkpoint. |
| Symbol/MEP training | 0% | No prepared data, completed run, or checkpoint. |
| Overall supervised AI training | 12% | 3 evidenced milestones out of 25 across the five families. |

## Production training sequence

## Task 6A — in-domain room/space dataset readiness

**Audit date:** 2026-09-01. **Scope:** local workspace and repository references only; no data was downloaded and no model was trained.

### Evidence-based source inventory

| Source | Physically available | Real in-domain AEC | Commercial-training rights evidenced | Counted for fine-tuning | Decision |
|---|---:|---:|---:|---:|---|
| Customer/partner construction sheets | No | N/A | No | 0 | Required next source; obtain explicit contractual consent and de-identify before intake. |
| `takeoff-house-plan-test.jpg` | One file | No evidence; test plan | No provenance record | 0 | Excluded. A file in the workspace is not rights evidence or a representative project. |
| `output/pdf/takeoff-dimensioned-floor-plan.pdf` | One generated file | No; synthetic test artifact | No source-rights record | 0 | Excluded from in-domain and golden counts. May remain a software fixture only. |
| Playwright vector PDF fixture | Generated in test code | No; deterministic synthetic fixture | Repository-owned test code | 0 | Excluded from model evaluation because it cannot represent real AEC domain performance. |
| ResPlan `spaces_v1` | Yes, 16,296 rendered plans | No; vector-derived pretraining domain | Yes, CC BY 4.0 with pinned provenance | 0 in-domain; retained as pretraining | Do not relabel it as customer-domain data. It remains the verified baseline source. |
| Hugging Face `Siddartha96/takeoff-spaces-v1` | Referenced private archive | No; the same ResPlan corpus | Existing pinned ResPlan provenance | 0 in-domain | No separate in-domain Hugging Face dataset reference was found. |
| Kaggle/Colab notebook inputs | Reference only | No; notebooks point to the ResPlan HF archive | No additional dataset | 0 | All notebook cells are unexecuted; they do not prove data acquisition or annotation. |
| CubiCasa5K | Yes: official 5,000-plan ZIP and external extracted copy | No, not TakeOff customer AEC; residential floor-plan source | **No commercial permission.** Official GitHub says CC BY-NC 4.0; Zenodo metadata says CC BY-NC-SA 4.0. Both prohibit commercial use. | 0 | Research audit only. Obtain a separate commercial license or exclude it from production training. |
| RPLAN / HouseGAN, Structured3D, CVC-FP, SESYD | References/scaffolds only; data absent | No verified in-domain material | No approved commercial-use evidence in this workspace | 0 | Not counted and not acquisition targets for Task 6A. |

**Current actual state:** 0 real in-domain sheets available, 0 rights-cleared usable sheets, 0 annotated sheets, and 0 golden sheets. Dataset sheet preparation is therefore **0% (0/400 target)**. The completed policies and validation tooling do not inflate the data-completion percentage.

### CubiCasa5K uploaded-archive audit

**Status: RESEARCH-ONLY / COMMERCIAL-BLOCKED.** CubiCasa5K must not be converted into a TakeOff.ai production dataset, merged with `spaces_v1`, or used for model training under the currently verified terms. Preserve the archive and completed audit artifacts unchanged. Resume CubiCasa work only after written permission expressly covering TakeOff.ai's commercial ML training and intended model use is reviewed and recorded.

The uploaded `E:\Takeoff_datasets\cubicasa5k.zip` is 5,469,495,706 bytes. Its MD5 `0ce0b203d1e3c125b51087b219bd23b9` exactly matches official Zenodo record `10.5281/zenodo.2613548`; SHA-256 is `a4a3398534d6abb7db7b8c6ca8877a6edf18897dcbd20f4582b3fdd3c46632a5`, and the full ZIP CRC check passed. The original remains unchanged. The working copy is outside Git at `E:\Takeoff_datasets\datasets\raw\cubicasa5k`.

Verified contents are 5,000 annotated plan folders, 6,171 original floor pages, 6,171 scaled counterparts, 12,342 PNG files, 5,000 SVG annotations, and 1,032,432 SVG polygons. Official split lists contain 4,200 train / 400 validation / 400 test plan folders (5,169 / 496 / 506 original pages) with no duplicate paths, missing paths, or direct project overlap.

All PNGs and SVGs passed parsing; there are no empty files or missing original/scaled pairs. Two valid scaled pages are 14,304 × 6,316 pixels and require explicit conversion resource limits. Exact content duplicates remain: 38 cross-plan PNG hash groups and 16 duplicate SVG groups. Ten PNG groups and six SVG groups cross official split boundaries; the six SVG groups affect 12 plans. These must be removed/reassigned at plan level before any research benchmark.

The SVG taxonomy contains 32 space labels, 131,523 walls, 49,945 doors, 44,009 windows, 4,632 stairs, 15,663 railings, 11,942 columns, and 145,069 fixed-furniture groups across 66 classes. The current converter is not suitable for full conversion: it uses only `F1`, invents a periodic split rather than preserving/de-duplicating official splits, exports only space polygons, omits wall/door/window outputs, and does not resolve every nested SVG transform.

Current seven-class mappings require review. `Room→living`, `Outdoor→balcony`, `Garage/Utility→storage`, `Sauna→bathroom`, and `Den→living` are unsafe generalizations. This archive has no `Balcony` space label and represents stairs as architectural objects rather than a `Space` label. `Undefined` (11,005), `Outdoor` (7,852), `Entry` (4,211), `UserDefined` (1,856), and other unsupported labels cannot be silently coerced.

The uploaded ZIP contains no license/provenance document. The official GitHub LICENSE states CC BY-NC 4.0 while Zenodo metadata states CC BY-NC-SA 4.0. Both contain a NonCommercial restriction, so commercial TakeOff.ai training is **not permitted under current evidence**. No conversion, merge, or training was performed. Detailed evidence is in `app/backend/ml/datasets/CUBICASA5K_AUDIT.md` and `cubicasa5k_audit_manifest.json`.

### Commercial-use alternative dataset register

This is a metadata-and-license review only; no candidate was downloaded. `Commercial training allowed = YES` means the published dataset license permits commercial use in principle, subject to attribution, notice, copyleft, provenance, privacy, and distribution obligations. It does **not** bypass the TakeOff.ai source-intake gate or replace legal review for a production model release. Candidates with noncommercial or missing data licenses were excluded. Modified Swiss Dwellings is not listed separately because it is a processed derivative of Swiss Dwellings and would create source-lineage overlap rather than independent evidence.

| Priority | Dataset | Source | Verified size | Annotations | Rooms supported | Walls supported | Doors/windows supported | Published license | Commercial training allowed | Provenance confidence | Suitability for TakeOff.ai / required caution |
|---:|---|---|---:|---|---|---|---|---|---|---|---|
| 1 | Swiss Dwellings v3.0.0 | [Official Zenodo record](https://zenodo.org/records/7788422) | 45,176 apartments, about 370,000 rooms in about 3,100 buildings; about 520,000 areas, 1.7M separators, and 715,000 openings | Metric WKT geometries with site/building/floor/plan/unit/area identifiers, semantic entity types/subtypes, elevation and height | **Yes.** Typed areas include living, kitchen, bathroom, balcony and other residential/public/commercial space types | **Yes.** Walls/railings/columns are explicit separator geometries | **Yes.** Doors and windows are explicit opening geometries | CC BY 4.0 (dataset); attribution required | **YES** | **High.** Official institutional Zenodo release; source procurement and manual QA are documented | **Best overall geometry source** for room, wall and opening pretraining plus metric validation. It is vector/BIM-derived Swiss data, not scanned construction sheets; render multiple drawing styles and retain project-level splits. |
| 2 | ResPlan | [Official repository](https://github.com/m-agour/ResPlan) and [dataset release](https://www.kaggle.com/datasets/resplan/resplan) | 17,000 residential plans; 137,131 room polygons; canonical 13,053 / 1,632 / 1,632 split plus 683 augmentations | Shapely vector polygons, metric coordinates and typed NetworkX connectivity graphs; 17-category taxonomy | **Yes.** Bedroom, bathroom, kitchen, living, balcony and related spaces | **Yes.** Wall polygons | **Yes.** Door, front-door and window polygons/graph edges | CC BY 4.0 for data; MIT for code | **YES** | **Medium.** Dataset release is explicit, but source drawings came from public real-estate listings and source platform identities are withheld | **Already useful and already represented by `spaces_v1`.** Use only the corrected release and rebuild project/near-duplicate-safe splits; do not count it as new in-domain AEC evidence. |
| 3 | SFC-A68 v1.0.2 | [Official TU Wien Zenodo record](https://zenodo.org/records/14245850) | Entire floors from 275 multi-unit apartment buildings in 13 countries; 250.1 MB release | Linked tabular, graph and multi-view image representations; 22 space-function and 6 space-access-element classes | **Yes.** Fine-grained residential, service, sanitary, circulation and external-space functions | **Partial.** Layout/context representations exist, but this is primarily a function/access classification benchmark rather than estimator-grade wall-mask ground truth | **Doors: yes**, through six access-element classes; **windows: limited/contextual**, not a dedicated TakeOff window benchmark | GPL-3.0 | **YES**, with GPL obligations | **High.** Dataset copyright, authors, institution, version and license are stated in the official record | Strong small, diverse **room/access-function validation and fine-tuning supplement**. Keep its 275 source buildings grouped; obtain legal review of GPL obligations before distributing trained artifacts or converted labels. |
| 4 | MLStructFP | [Official project repository](https://github.com/MLSTRUCT/MLStructFP) | 954 large floor-plan PNGs, 954 floor/slab records and 70,873 wall rectangles; images roughly 6,500–9,500 px | JSON floor/slab/wall geometry and metadata with metric scale; PNG plan images | **Limited.** Loader exposes room/item structures, but published dataset emphasis and verified counts are walls/slabs | **Yes.** Detailed wall rectangles, thickness, angle, length and partition metadata | **No verified dedicated door/window labels** | MIT repository license | **YES**, provisionally | **Medium.** Official project is MIT-licensed, but the gated dataset download must be checked to confirm that the same license accompanies the raw release | Best focused candidate for **wall segmentation/vectorization and thickness**. Do not ingest until the downloaded package's license and source provenance match the public repository claim. |
| 5 | ResBIM | [Official repository](https://github.com/RogerLiang0725/ResBIM) | 1,000+ paired synthetic samples; full release about 7 GB | Fully parametric RVT BIM paired with annotated 2D floor plans; convertible to plans, elevations, sections and point clouds | **Yes, derivable from semantic BIM**, but exact TakeOff seven-class mapping needs inspection | **Yes, derivable from BIM geometry** | **Yes, derivable from BIM openings** | MIT | **YES** | **Medium-high.** Official authors release a synthetic dataset and source under MIT; reported failure cases are documented | Strong **synthetic geometry and 2D-to-BIM supplement**, especially for walls/openings and controlled views. Audit class schema and remove documented failed samples; it cannot replace real AEC raster/vector sheets. |

**Decision:** prioritize a metadata/sample-only intake of Swiss Dwellings first. Keep ResPlan as the existing pretraining lineage, then evaluate small samples and exact license files from SFC-A68, MLStructFP, and ResBIM before any bulk download or conversion. HouseExpo was excluded despite an MIT repository because it is derived from SUNCG and the repository license does not resolve the underlying source-data rights. FloorPlanCAD and CubiCasa5K were excluded because their verified licenses contain NonCommercial restrictions.

### Swiss Dwellings v3 metadata/sample intake

**Metadata decision date:** 2026-09-01. **Complete-building sample audit date:** 2026-09-02. **Scope:** official metadata and published schema plus a bounded, checksum-verified audit of eight complete buildings from the official archive. The archive and all extracted/sample data remain outside Git under `E:\Takeoff_datasets\swiss_dwellings`; no full-dataset conversion or training was run.

#### Official identity, rights, and provenance

- Official release: **Swiss Dwellings v3.0.0**, Zenodo record `7788422`, DOI [`10.5281/zenodo.7788422`](https://doi.org/10.5281/zenodo.7788422), file `swiss-dwellings-v3.0.0.zip`, MD5 `3b7915ecd5bf8e492a3e78c598b74123`.
- Authors: Matthias Standfest, Michael Franzen, Yvonne Schröder, Luis Gonzalez Medina, Yarilo Villanueva Hernandez, Jan Hendrik Buck, Yen-Ling Tan, Milena Niedzwiecka, Rachele Colmegna.
- The official record declares the **dataset** under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). It permits sharing and adaptation, including commercial use, provided TakeOff.ai gives appropriate attribution, links the license, indicates modifications, and applies no additional legal or technical restrictions to the licensed data. The Archilyse processing/tooling license is separate and must not be confused with the dataset license.
- Provenance documentation says Archilyse AG obtained existing building plans from commercial clients, converted them to a georeferenced semantic representation, and applied manual quality assurance. This supports **real underlying building geometry**, not release of the original client drawings.
- Production intake remains subject to preserving DOI/version/checksum/attribution and recording renderer and taxonomy transformations. No privacy or customer-sheet rights are inherited beyond the released CC BY dataset.

#### Published structure and split identity

The archive is documented as four CSV files: `geometries.csv` (WKT elements), `simulations.csv` (area-level simulation data), `locations.csv` (building-level metadata), and `location_ratings.csv` (building-level ratings). No raster PDF, PNG, TIFF, CAD, or original contractor sheet is documented in v3.

The safest hierarchy is:

`site_id -> building_id -> plan_id (layout template) + floor_id (floor occurrence) -> unit_id/apartment_id -> area_id -> area/separator/opening/feature rows`.

The published example exposes `site_id`, `building_id`, `plan_id`, `floor_id`, `apartment_id`, `unit_id`, `area_id`, `unit_usage`, `entity_type`, `entity_subtype`, metric WKT geometry, elevation, and height. `plan_id` may be reused for repeated layouts on multiple floors, and apartment IDs are not documented as globally unique. The required split group is therefore **the complete `(site_id, building_id)`**, augmented by a cross-building geometry-near-duplicate cluster. All plans, floors, units, variants, and derived renders belonging to that group must remain in one split. Random apartment/unit splitting is prohibited.

Recommended development split: 80% train / 10% validation / 10% secondary test by building-cluster, stratified only at the building-group level by usage, taxonomy, size, and complexity. Keep one representative or one weighted group for repeated `plan_id` layouts. Swiss Dwellings must not be TakeOff.ai's final golden evaluation set.

#### Semantic taxonomy and safe TakeOff.ai mapping

Current official Archilyse semantic definitions include the following relevant area families. The complete-building sample below now verifies the observed subset; enum members absent from the sample remain unverified.

| Proposed TakeOff.ai label | Direct Swiss subtype(s) | Keep separate or review; do not force-map |
|---|---|---|
| bedroom | `BEDROOM` | `MEDICAL_BEDROOM`, `DEDICATED_MEDICAL_BEDROOM`, `STUDIO`, `ROOM` |
| bathroom | `BATHROOM` | `SANITARY_ROOMS`, cloakrooms and medical sanitary uses |
| kitchen | `KITCHEN` | `KITCHEN_DINING`, `COMMON_KITCHEN`, canteen |
| living | `LIVING_ROOM` | `LIVING_DINING`, `COMMUNITY_ROOM`, `ROOM`, `STUDIO` |
| dining | `DINING` | `LIVING_DINING` and `KITCHEN_DINING` are composite labels |
| corridor | `CORRIDOR` | `CORRIDORS_AND_HALLS`, transport circulation |
| storage | `STOREROOM` | basement compartments, bike/pram storage, warehouse, archive, cold storage |
| balcony | `BALCONY` | loggia, terrace, patio, arcade, winter garden |
| office | `OFFICE` | office space, open-plan office, meeting/design/reception/control rooms |
| utility | No single safe subtype | technical area, wash/dry, building-services and supply rooms require explicit labels |
| stairs | `STAIRCASE` area | `STAIRS` feature geometry is a different annotation target |
| entry/lobby | `FOYER`, `LOBBY` | entrance door is an opening, not an area |
| generic/other room | `ROOM`, `NOT_DEFINED` | retain as unmapped/other until frequency and visual review |

The broader upstream enum also contains residential exterior/void/shaft/parking and many commercial, public, educational, medical, industrial, transport, and building-services classes. Composite and specialty types must remain source labels or explicit exclusions; they must not be collapsed into the current seven-class `spaces_v1` taxonomy merely to increase sample count.

#### Separator and opening supervision

- Separator types are `WALL`, `COLUMN`, `RAILING`, `AREA_SPLITTER`, and `NOT_DEFINED`. Metric WKT is suitable for wall masks and metric geometric validation. Wall centerlines and topology can be deterministically derived, but are **not direct ground-truth labels**. Internal versus external walls are not directly encoded by the separator type and would require reviewed adjacency/envelope derivation. Metric lengths are derivable only after a documented centerline/polygon measurement rule.
- Opening types are `DOOR`, `ENTRANCE_DOOR`, `WINDOW`, `WINDOW_ENVELOPE`, `WINDOW_INTERIOR`, and `NOT_DEFINED`; door subtype distinguishes default/winged from sliding. This is suitable for door, entrance-door, and window geometry supervision after observed-class counts and geometry QA. It does not provide estimator-grade fire ratings, leaf counts, hardware, materials, or full construction schedules.

#### Deterministic rendering requirement

Vision training requires a renderer because raster plan images are not included. The future renderer must group a complete floor, parse and validate WKT without altering the source, retain original metric coordinates, calculate explicit bounds and fixed pixels-per-metre (not a guessed DPI), and rasterize stable layers for areas, separators, openings, and selected features. Each output must include a lossless image, masks/YOLO labels, and metadata containing all site/building/plan/floor/unit IDs, source DOI/version/checksum, taxonomy map, renderer version/profile, coordinate transform, and pixels-per-metre. Split assignment must happen before rendering; every style variant remains with its source building group.

#### Domain gap, integrity risks, and production role

Swiss Dwellings represents manually digitized semantic geometry derived from real building plans. It is **not synthetic underlying geometry**, but any raster produced from it will be a synthetic rendering. It is not the original contractor construction drawing or architectural-documentation sheet: title blocks, dimensions, notes, symbols, revision clouds, scan noise, MEP layers, details, and multi-sheet context are absent. It is predominantly Swiss residential/apartment data, creating geographic, asset-type, drafting-style, and document-domain gaps against TakeOff.ai customer drawings.

Published scale is approximately 45,176 apartments, 370,000 rooms, and 3,100 buildings, with about 520,000 areas, 1.7 million separators, 715,000 openings, and 315,000 features. The source documentation reports manual QA with apartment-area deviation capped at 5% and median 1.2%, but that does not prove all WKT or labels are valid. The original corpus has material repeated-layout risk because `plan_id` can span floors; the Modified Swiss Dwellings publication also documents aggressive removal of non-residential-like layouts, near duplicates, small plans, and disconnected geometries from a derivative subset. Before approval, intake must measure malformed/empty WKT, missing/unknown labels, floors without openings, disconnected/extreme geometry, exact subtype balance, exact duplicate hashes, and cross-building geometry fingerprints.

Recommended roles relative to checksum-pinned ResPlan `spaces_v1`:

| Use | Decision |
|---|---|
| A. Room/space pretraining | **Yes**, with source-aware taxonomy and building-level splits |
| B. Customer-domain room fine-tuning | **No** as the final fine-tune; acceptable as an intermediate geometry-domain stage before rights-cleared customer sheets |
| C. Wall training | **Yes**, after derived-label QA and deterministic rendering |
| D. Door/window training | **Yes**, after subtype-frequency and geometry validation |
| E. Geometry pretraining | **Yes — highest-value role** |
| F. Final golden evaluation | **No**; at most a secondary unseen-building geometry benchmark |

**Archive gate completed:** the official 931,868,205-byte ZIP was downloaded only after explicit approval, preserved unchanged outside Git, and verified against published MD5 `3b7915ecd5bf8e492a3e78c598b74123`. ZIP CRC validation passed before extraction. The extracted source remains immutable; only eight complete buildings and three deterministic plan renders were used for the bounded audit.

#### Complete-building sample intake result

**Result date:** 2026-09-02. **Status: SAMPLE VALIDATED; FULL CONVERSION NOT YET APPROVED.** The official release provides no smaller building-complete sample, so the explicitly approved checksum-pinned archive was used only to extract a representative bounded sample. The immutable archive is `E:\Takeoff_datasets\swiss_dwellings\raw\swiss-dwellings-v3.0.0.zip`; official Zenodo metadata is preserved in the external manifests directory.

The selector retained complete `(site_id, building_id)` membership for eight sites/buildings spanning 34 plan IDs, 47 floor IDs, 641 units/apartments, and 22,904 geometry rows. Building profiles range from 0 to 497 units, 1 to 22 floors, 1 to 13 plan IDs, 34 to 11,685 geometry rows, and sparse garage through dense mixed/public-like geometry. Related bounded extracts contain 1,425 simulation rows, seven location rows, and seven location-rating rows. Building `11891/18565` has complete geometry but no matching location/rating row; geometry hierarchy and sampling remain valid, but associated-table absence must be represented explicitly rather than imputed.

Observed geometry counts:

| Entity family | Observed subtype counts |
|---|---|
| Areas | `ROOM` 522; `SHAFT` 670; `BATHROOM` 377; `CORRIDOR` 244; `KITCHEN` 206; `STOREROOM` 144; `LIVING_ROOM` 128; `BALCONY` 123; `BEDROOM` 118; `ELEVATOR` 98; `LIVING_DINING` 74; `STAIRCASE` 71; `CORRIDORS_AND_HALLS` 61; `OFFICE_SPACE` 36; remaining observed area subtypes 64 |
| Separators | `WALL` 12,176; `COLUMN` 774; `RAILING` 621 |
| Openings | `WINDOW` 1,753; `ENTRANCE_DOOR` 1,620; `DOOR` 1,223 |
| Features | `SINK` 374; `KITCHEN` 324; `TOILET` 305; `SHOWER` 250; `STAIRS` 195; `WASHING_MACHINE` 116; `BUILT_IN_FURNITURE` 101; `ELEVATOR` 98; `BATHTUB` 18 |

Integrity and hierarchy evidence:

- required site/building/plan/floor IDs were present; unit-to-building conflicts: **0**;
- malformed or missing WKT: **0**; invalid geometries: **0**; empty geometries: **0**; zero-area polygons: **0**; disconnected geometries: **0**; extreme-coordinate rows: **0**;
- exact duplicate full CSV rows: **0**;
- 45 of 47 floors contain rooms, separators, openings, doors, and windows; one floor lacks windows and one lacks doors; no floor lacks rooms, separators, or all openings;
- metric extents are plausible on all 47 floors: width 10.459–104.131 m and height 11.973–81.883 m; source coordinates are consistently usable as metres;
- all 2,843 door/entrance-door geometries and all 1,753 window geometries intersect or touch the floor wall union (maximum measured distance 0 m). This validates geometric alignment, not estimator attributes such as fire rating, hardware, or swing semantics.

Duplicate/leakage evidence is material. Exact geometry hashing found 3,843 repeated-geometry groups containing 18,742 rows: 3,139 groups span floors, 1,162 span plan IDs, and 704 occur on the same floor. Same-floor repetition keeps identical entity semantics and is associated with multi-unit/shared boundaries. Six plan IDs recur across floors. No exact or near-duplicate complete-floor geometry was found across the eight sampled buildings. Production conversion must therefore deduplicate or weight geometry at the floor level and keep all repeated plans/floors from a building in one split; row-level or apartment-level splitting is prohibited.

The sample-only renderer produced three plans at fixed 16 pixels/metre. Each output contains a composite, room mask, separator mask, opening mask, metric source bounds, invertible pixel/metre transform, source IDs, source checksum, class maps, renderer version, and per-file hashes. Independent rerendering produced identical hashes for every output. Visual inspection confirmed the semantic layers align with the composite. Rendered rasters remain synthetic views of real semantic building geometry and do not close the customer-document domain gap.

**Decision:** the sample is **PARTIAL** for the production pretraining pipeline. It validates Swiss Dwellings for room/geometry pretraining, wall masks, door/window geometry supervision, and metric validation. Before any full preprocessing, approve a source-label mapping/exclusion policy, a floor-level shared-geometry deduplication/weighting rule, and a bounded conversion pilot. It remains unsuitable as the final TakeOff.ai customer-drawing golden set. Full conversion, merging with `spaces_v1`, and all training remain prohibited pending that gate.

#### Bounded preprocessing pilot

**Result date:** 2026-09-08. **Status: PILOT CONVERTED AND VALIDATED; FULL CONVERSION NOT APPROVED.** Conversion used only the external eight-building sample and enforced hard limits of 10 buildings and 100 floor occurrences. Output is external at `E:\Takeoff_datasets\swiss_dwellings\processed\pilot-v1`; no raw or generated dataset artifact was placed in Git.

The pilot converted **34 unique plan IDs / 47 floor occurrences**. Its 22,904 source geometry rows became **19,515 canonical floor-local geometries**: 2,956 areas, 11,139 separators, 3,639 openings, and 1,781 features. The converter collapsed 3,389 repeated rows into 2,905 shared canonical records, with at most four original rows per record, while preserving all 22,904 source row references, apartment IDs, unit IDs, area IDs, source type/subtype, metric WKT, source version, and deterministic geometry IDs. Deduplication requires identical floor IDs, entity type, source subtype, and normalized WKT, so adjacent or differently typed coincident structural geometry is retained.

The canonical TakeOff.ai pilot taxonomy is:

- spaces: `bedroom`, `bathroom`, `kitchen`, `living`, `living_dining`, `corridor`, `storage`, `balcony`, `office`, `utility`, `stairs`, `entry_lobby`, `generic_room`, `shaft`;
- separators: `wall`, `column`, `railing`;
- doors: `door`, `entrance_door`;
- windows: `window`, `window_envelope`, `window_interior`.

Every source mapping and exclusion is recorded in `app/backend/ml/datasets/swiss_dwellings_taxonomy_v1.json`. The pilot deliberately excluded 157 ambiguous/specialty area instances from room masks while retaining them in metric supervision: `ARCHIVE`, `BASEMENT`, `BASEMENT_COMPARTMENT`, `CARPARK`, `ELECTRICAL_SUPPLY`, `ELEVATOR`, `ELEVATOR_FACILITIES`, `FACTORY_ROOM`, `GARAGE`, `GARDEN`, `HEATING`, `LIGHTWELL`, `MEETING_ROOM`, `OFFICE_TECH_ROOM`, `OUTDOOR_VOID`, `PRAM_AND_BIKE_STORAGE_ROOM`, `SANITARY_ROOMS`, `SHELTER`, `TERRACE`, `TRANSPORT_SHAFT`, `VEHICLE_TRAFFIC_AREA`, and `VOID`. Composite `LIVING_DINING` remains its own class rather than being forced into living or dining.

Generated supervision totals are **2,799 room instances**, **9,931 wall geometries/mask instances**, **1,938 door labels** (`door` 1,206; `entrance_door` 732), and **1,701 window labels**. The converter also retained 588 columns and 620 railings. One garage-only floor is a deliberate negative room sample, one floor has no door label, and one has no window label; no floor has an empty wall mask. All 3,639 deduplicated door/window labels remain within 0.05 m of wall geometry, with measured maximum distance 0 m.

Each floor output contains a deterministic RGB geometry render, semantic and instance room masks, separator/door/window masks, YOLO door/window boxes, metric WKT supervision, complete source provenance, and hashes. Rendering uses fixed **16 pixels/metre**, 2 m metric padding, no stretching or adaptive rescaling, an explicit invertible world/pixel transform, and a hard 4,096-pixel dimension ceiling. All 47 outputs passed image/label dimension, mask-domain, transform round-trip, WKT/provenance, and opening-alignment checks. Three independent rerenders produced identical hashes.

Split assignment is building-cluster based: six buildings / 35 floors in train, one building / four floors in validation, and one building / eight floors in test. All floors, units, repeated layouts, and outputs from a building stay together. Exact and 0.10 m Hausdorff near-duplicate floor checks found **zero cross-building pairs** in the pilot; building split leakage was **zero**.

**Production gate at pilot completion:** the pilot was **PARTIAL / conditionally training-ready for geometry pretraining**, not customer-domain final training. Full conversion was held pending review of the 14-class space taxonomy and 157 exclusions, the floor-local shared-geometry policy, representative label overlays, and a negative/rare-class weighting recommendation. Swiss Dwellings remains prohibited as the final customer-drawing golden set, and no model training is authorized by this pilot.

#### Taxonomy, deduplication, and representative visual QA gate

**Result date:** 2026-09-08. **Taxonomy review: PASS. Deduplication review: PASS. Technical full-conversion approval: YES. Training approval: NO.** The core taxonomy was retained unchanged. `swiss_dwellings_taxonomy_v1.json` now gives every non-training source area an explicit recoverable state: `REVIEW` 127 instances, `MAP_TO_OTHER` 6, and `IGNORE_FOR_CURRENT_MODEL` 24. `other_aec` is provenance-only, not a new training class. All 157 instances retain source subtype, metric WKT, deterministic geometry ID, source row numbers, apartment/unit/area relationships, candidate mapping, decision state, and reason.

The full 157-instance mapping decision table is documented in `app/backend/ml/datasets/SWISS_DWELLINGS_TAXONOMY_REVIEW.md`. No unclassified source semantic remained in room, separator, door, or window targets. Ambiguous candidate mappings remain excluded from present masks until domain approval; they were not discarded or silently collapsed.

Deduplication reconciliation proved **zero nonduplicate semantic-geometry loss** and **zero source-relationship loss**. All 22,904 input row relationships reconcile to 19,515 canonical geometries. Shared walls are represented once geometrically while every contributing unit relationship remains available. Training frequency and future weights are based on canonical geometry only; source-row multiplicity never increases training weight. A repeat-in-place regression also fixed and now tests payload-hash determinism when an output directory already contains `hashes.json`.

Eight distinct floor occurrences were visually reviewed:

| Review case | Site/building/plan/floor | Evidence |
|---|---|---|
| Simple residential | `1851/2900/8224/13276` | 34 raw / 34 canonical rows, one unit, six mapped spaces |
| Multi-unit residential | `456/1105/3148/4843` | 2,069 raw / 1,694 canonical rows, 92 units |
| Large building | `456/1105/3148/4842` | large curved multi-wing floor, 92 units |
| Multi-floor building | `11891/18565/43780/50772` | building with 22 floors; 422 raw / 366 canonical rows |
| Dense walls/openings | `456/1105/3147/4839` | 2,263 raw / 1,797 canonical rows; densest selected layout |
| Rare room classes | `11692/18240/42297/48825` | office, utility, entry/lobby, stairs and reviewed specialty semantics |
| Negative garage-only | `11719/18278/42441/49025` | zero current-model rooms; `GARAGE [MAP_TO_OTHER]` remains visible/recoverable |
| Shared-wall case | `456/1105/3148/4841` | 375 repeated ownership rows collapsed while visible wall geometry remains complete |

The review overlays show source geometry, canonical room labels, walls, doors, windows, and non-training state labels. Visual inspection found no missing room/wall/opening layer, misregistered opening, clipped plan, or deduplication gap. Dense-plan text labels overlap at contact-sheet scale, but semantic masks and metric labels remain separate and valid; this is a review-presentation limitation, not training-label corruption.

Automated QA over all 47 pilot floors found: invalid polygons 0; empty geometries 0; orphan openings 0; openings beyond 0.05 m wall tolerance 0; overlapping mapped-room pairs 0; suspicious wall geometries 0; nonduplicate geometry loss 0; source relationship loss 0. The known empty outputs are one garage-only room-negative floor, one no-door floor, and one no-window floor; wall masks are nonempty on all floors.

Room-size screening flagged 562 mapped spaces below 1 m²: 559 shafts, two wash/dry utility spaces, and one storeroom. It flagged one corridor above 500 m². These are retained as class-appropriate or reviewable geometric extremes rather than silently deleted. No material label defect was established. Full conversion should continue reporting these distributions and permit later class-aware thresholds.

Measured imbalance is significant but manageable: spaces range from entry/lobby 10 and utility 14 to shaft 670 (67×); separators range from column 588 to wall 9,931 (16.9×); door versus entrance-door is 1.65×. Recommended initial policy is one contribution per canonical geometry, optional square-root inverse-frequency class sampling/loss weights capped at 0.5×–3×, negative-only floors capped near 10% of batches, and rare-class reporting/sampling rather than raw inverse-frequency weights. No weighting was implemented in this task.

**Decision:** no material taxonomy, registration, geometry, deduplication, or leakage defect blocks full Swiss Dwellings preprocessing. Full conversion is technically approved, but remains unexecuted pending an explicit task authorization. Model training remains **not approved** and must be authorized separately after full-conversion QA.

### Target acquisition and split

The first frozen version targets 400 representative sheets, within the approved 300–500 range:

| Split | Target sheets | Isolation rule | Use |
|---|---:|---|---|
| Train | 280 | Whole projects, including all pages/units/revisions, stay here only | Fine-tuning |
| Validation | 50 | Projects absent from all other splits | Epoch/model selection only |
| Test | 40 | Projects absent from train/validation/golden | Pre-release internal evaluation |
| Golden | 30 | Explicitly approved and untouched projects; allowed range 20–40 | Final baseline/candidate comparison and promotion only |

The deterministic splitter hashes opaque project IDs, preserves reviewed explicit assignments, and assigns an entire project at once. It never infers golden eligibility: every golden page must be marked `golden_approved=true` and `untouched=true`. Project, revision, page, customer, and near-duplicate leakage are blocked by the QA gate.

Each source-manifest record must include an opaque sample/project/sheet ID, source-relative image and YOLO label paths, split (when reviewed), rights status, commercial-training permission, a rights evidence reference, annotation approval/reviewers, difficult-case tags, and golden flags. It must not contain customer secrets or imply permission from possession alone.

### Annotation/class coverage decision

The first fine-tune preserves the deployed seven-class order: `living`, `bedroom`, `bathroom`, `kitchen`, `balcony`, `stair`, `storage`. Detailed geometry and ambiguity rules are frozen in `app/backend/ml/datasets/IN_DOMAIN_SPACES_ANNOTATION_GUIDELINES.md`.

Real construction plans expose a material taxonomy gap: corridor/hallway, dining, office/study, lobby, laundry, utility/mechanical/electrical, elevator, shaft, garage, porch/deck/patio, and generic rooms are not represented. Annotators must record these as reviewed exclusions and must not force them into the closest class. Open-plan living/kitchen regions are split only at defensible drawn or consistently documented boundaries. Class-expansion is a later evidence-based model decision after measuring exclusion frequency.

The dataset must cover open plans, partial rooms, corridor/shaft negatives, closets/storage, stairs, balconies, crop boundaries, text-heavy drawings, low-quality scans, and multi-unit plans. The configuration requires at least five tagged sheets for every difficult-case category and class-instance floors, with explicit rare-class coverage for balcony, stair, and storage.

### Executable QA gate

`validate_in_domain_spaces.py` blocks training readiness on:

- absent or non-commercial rights evidence;
- missing independent annotation approval or unfrozen golden records;
- project/revision leakage across train, validation, test, or golden;
- byte-identical or cross-split perceptual duplicate candidates;
- corrupt/unsupported files and images below the configured minimum resolution;
- missing image/label pairs, empty labels not explicitly approved as negatives, unknown classes, non-normalized, zero-area, or self-intersecting polygons;
- materially overlapping room masks;
- insufficient total/golden counts, empty project splits, class imbalance, or missing difficult-case coverage.

The preparation command never downloads data or overwrites a non-empty materialized dataset. It can create the deterministic split manifest and, only after sources exist, copy approved files into a canonical YOLO train/validation/test/golden layout with `groups.json` proving project membership.

### Golden evaluation and promotion contract

The current checksum-pinned checkpoint must first be run on the same frozen in-domain golden set to establish the comparable baseline. The published ResPlan metrics remain model-card context but cannot be used as an in-domain promotion baseline.

The frozen report must include overall/per-class mask precision, recall, mAP50, mAP50-95, matched-instance IoU and Dice, room-count exact accuracy/absolute error/percentage error, support counts, false-positive/false-negative review, and source/difficulty slices. Candidate promotion requires both mAP measures to improve by at least 0.03 over the in-domain baseline, precision/recall regressions no worse than 0.02, mean IoU at least 0.70, Dice at least 0.80, exact room-count accuracy at least 0.90, aggregate count error at most 5%, and no supported class regression above 0.03. Full rules are frozen in `app/backend/ml/datasets/GOLDEN_SPACES_EVALUATION.md`.

### Task 6A artifacts and readiness

- `app/backend/ml/datasets/in_domain_spaces_config.json` — targets, class order, QA thresholds, difficulty coverage, deterministic seed.
- `app/backend/ml/datasets/in_domain_spaces_source_manifest.json` — truthful empty intake inventory with exclusions and mandatory eligibility policy.
- `app/backend/ml/datasets/in_domain_spaces_source_manifest.schema.json` — versioned rights, provenance, privacy, integrity, and source-field contract.
- `app/backend/ml/datasets/in_domain_spaces_split_manifest.json` — truthful empty 280/50/40/30 target manifest.
- `app/backend/ml/datasets/in_domain_spaces_progress_report.json` — zero-based received/cleared/de-identified/annotated/reviewed/accepted reporting format.
- `app/backend/ml/datasets/IN_DOMAIN_SPACES_ANNOTATION_GUIDELINES.md` — seven-class policy, exclusions, difficult cases, review/freeze rules.
- `app/backend/ml/datasets/GOLDEN_SPACES_EVALUATION.md` — immutable golden protocol, metrics, and relative promotion gate.
- `app/backend/ml/datasets/SOURCE_INTAKE_CHECKLIST.md` — per-project/sheet provider evidence and controlled ingestion procedure.
- `app/backend/ml/datasets/DEIDENTIFICATION_WORKFLOW.md` — privacy redaction, metadata sanitization, geometry preservation, and independent review process.
- `app/backend/ml/datasets/FIRST_BATCH_SAMPLING_PLAN.md` — exact 60-sheet quota and first-batch class floors.
- `app/backend/ml/datasets/ANNOTATION_HANDOFF_PACKAGE.md` — human labeling package, ambiguity rules, review checklist, and acceptance gate.
- `app/backend/ml/datasets/prepare_in_domain_spaces.py` — deterministic project splitter and optional safe YOLO materializer.
- `app/backend/ml/datasets/validate_in_domain_intake.py` — pre-annotation eligibility and blocker report for rights, provenance, privacy, integrity, duplicates, and leakage.
- `app/backend/ml/datasets/validate_in_domain_spaces.py` — rights, leakage, duplicate, image, polygon, overlap, balance, and coverage validator.
- `app/backend/tests/test_in_domain_spaces_dataset.py` — regression coverage for split isolation and QA enforcement.
- `app/backend/tests/test_in_domain_spaces_intake.py` — regression coverage for intake eligibility and blocker classification.

### First-batch acquisition and ingestion gate

The first batch is fixed at 60 sheets: 15 residential single-family, 15 apartment/multi-unit, 10 commercial/retail, 10 office, and 10 hospitality. The cross-cutting source-format quota is 36 clean vector PDFs, 18 scanned raster sheets, and 6 native raster exports; complexity quota is 20 simple, 30 dense, and 10 mixed sheets. At least 30 sheets must come from genuine multi-page plan sets. These quotas do not authorize use: unavailable hospitality data remains a documented shortfall until the manifest is versioned to approve a substitution.

Every incoming record must state source owner, permission basis, commercial-training and redistribution decisions separately, confidentiality restrictions, de-identification requirement/status, opaque project ID, drawing type, discipline, revision, page/sheet number, original and eligible-derivative hashes/paths, intake date, rights evidence/reviewer/timestamp, provenance reference/recorder/timestamp, and integrity approval. The manifest stores only a reference to restricted rights evidence, not contracts or customer secrets.

The intake gate reports each sheet as `eligible` or `blocked`, with independent blocker counts for rights, provenance, de-identification, duplicate, corrupted file, and project-leakage risk. It verifies the derivative bytes against SHA-256 and parses PDF/image integrity. Permission to redistribute is not required for internal commercial training, but a `NO` decision keeps the material restricted and out of public repositories.

Required de-identification produces a separately hashed derivative and a review log. It removes identifying title-block/revision/client/contact metadata while preserving room geometry, dimensions, scale, page size, and resolution. The original remains access-controlled and is never overwritten. Intake eligibility is now mandatory in both the project splitter and final training-dataset validator; annotation/review remains a separate later gate.

First-batch minimum instance floors are living 40, bedroom 90, bathroom 70, kitchen 40, balcony 15, stair 15, and storage 25. Unsupported corridors, dining, office/study, lobby, laundry, utility/mechanical/electrical rooms, elevators, shafts, garages, and exterior-space variants are counted as taxonomy gaps, not coerced into target labels.

Progress remains: received 0 / rights-cleared 0 / de-identified 0 / annotated 0 / reviewed 0 / accepted 0. No acquisition or readiness percentage changes until evidence-backed sheet records exist.

**Fine-tuning readiness: NO.** The pipeline is ready to accept reviewed data, but there are no approved in-domain sheets to prepare or annotate. The single next action is to obtain the first provider package with signed commercial-training permission and begin filling the exact 60-sheet intake manifest, starting with a rights-cleared 10–15-sheet pilot from one or more clearly identified projects.

### Phase A — Room/Space segmentation

- **Dataset needed:** Existing ResPlan `spaces_v1` for pretraining plus at least 300-500 rights-cleared, representative customer AEC sheets with polygon labels; reserve 20-40 entire projects/sheets as an untouched golden set. Target 1,000+ in-domain sheets after the first release.
- **Architecture:** Continue YOLOv8m-seg initially to preserve the existing inference schema and permit direct comparison with the current baseline.
- **Training command:** `python -m ml.training.run_training --data data/spaces_v2/data.yaml --task spaces --epochs 100 --imgsz 1280 --no-promote`, initialized from the current ResPlan checkpoint after recording that provenance.
- **Promotion metrics:** Existing mandatory gate: mIoU >= 0.70 and aggregate measurement error <= 5%; also require reporting mask precision/recall, mask mAP50, mask mAP50-95, Dice, per-class metrics, and raster/vector/domain slices. No promotion on ResPlan validation alone.
- **Artifact:** Versioned `best.pt`, SHA-256, model card, dataset version ID, golden report, and immutable HF/S3 revision.
- **Integration:** `ai.inference.InferenceEngine` locally and `ai/space/app.py` remotely through the existing `predict_spaces` response schema.

### Phase B — Wall detection/vectorization

- **Dataset needed:** At least 500 representative sheets for a first model and 1,000+ for production, labeled with wall masks, centerlines, openings, interior/exterior type, and—where readable—thickness. Split by project/revision.
- **Architecture:** Segmentation model for wall pixels/instances plus the existing deterministic centerline/vectorization and topology post-processing. The three-class 32x32 patch CNN may be an auxiliary classifier, not the authoritative wall geometry model.
- **Training command:** Planned command after adding the `walls` task to the existing runner: `python -m ml.training.run_training --data data/walls_v1/data.yaml --task walls --epochs 150 --imgsz 1280 --no-promote`. The current runner does not yet accept `walls`; do not pretend this command works today.
- **Promotion metrics:** Wall-mask IoU >= 0.75, Dice >= 0.85, centerline precision/recall >= 0.85, opening-aware topology checks, and wall-LF error <= 5% on the golden set.
- **Artifact:** `walls-best.pt` plus vectorization configuration and golden report.
- **Integration:** `ai/wall_vectorization.py`, canonical linear annotations/measurements, and estimator wall quantities.

### Phase C — Door and window detection

- **Dataset needed:** At least 3,000 labeled door/window instances across 300+ sheets for a first production candidate, with class-balanced typed doors/windows and difficult negatives; target 10,000+ instances.
- **Architecture:** YOLOv8m detection for robust count/localization first; add segmentation only where swing/opening geometry materially improves takeoff.
- **Training command:** `python training/train_yolov8_objects.py --data datasets/openings_yolo --epochs 300 --imgsz 1280 --model yolov8m.pt --output ai/models/opening_detect` after freezing a canonical opening-only taxonomy.
- **Promotion metrics:** Per-class precision/recall >= 0.85, mAP50 >= 0.85, mAP50-95 >= 0.60, count error <= 5%, and false-positive review on dense plans.
- **Artifact:** `yolov8-openings.pt`, checksum, model card, dataset version, and golden report.
- **Integration:** Existing symbol/object result conversion into canonical door/window annotations and quantities.

### Phase D — Symbols/fixtures

- **Dataset needed:** At least 5,000 labeled architectural/circulation/fixture instances across 500+ sheets, with source-specific splits and negative sheets. Start with sink, toilet, bathtub, shower, major appliances, stairs, and elevator.
- **Architecture:** YOLOv8m detection using the existing 18-class object scaffold; use segmentation only for classes whose geometry affects measurement.
- **Training command:** `python training/train_yolov8_objects.py --data datasets/symbols_v1 --epochs 300 --imgsz 1280 --model yolov8m.pt`.
- **Promotion metrics:** Macro mAP50 >= 0.85, mAP50-95 >= 0.60, per-class recall >= 0.80, and count error <= 5%; report rare-class support.
- **Artifact:** `ai/models/object_detect/yolov8-objects.pt` plus registry/model-card artifacts.
- **Integration:** Raster symbol detection, canonical count annotations, search regions, quantities, and estimating assemblies.

### Phase E — MEP symbols

- **Dataset needed:** Separate discipline-aware electrical, plumbing, HVAC, and fire-protection sheets; at least 500 sheets and 10,000 labeled instances for the first broad candidate, with symbol legends and office/region variation. Expand beyond the current minimal outlet/switch/light/HVAC labels only after taxonomy approval.
- **Architecture:** Discipline-specific YOLO detectors or a shared detector with discipline conditioning; CLIP can rank/review candidates but must not be the sole authoritative counter.
- **Training command:** Planned canonical command after approved MEP taxonomy: `python training/train_yolov8_objects.py --data datasets/mep_v1 --epochs 300 --imgsz 1280 --model yolov8m.pt --output ai/models/mep_detect`.
- **Promotion metrics:** Macro and per-discipline mAP50 >= 0.85, mAP50-95 >= 0.60, critical-class recall >= 0.90, and count error <= 5%, with customer/legend holdouts.
- **Artifact:** Versioned MEP checkpoint(s), checksums, model cards, dataset IDs, and discipline-level golden reports.
- **Integration:** Symbol inference, canonical count annotations, MEP conditions, search, estimating, and exports.

### Phase F — Evaluation and model promotion

- **Dataset needed:** Immutable, rights-cleared golden sets separated by customer/project and by vector, scanned, and raster source type; no training/threshold tuning on these samples.
- **Architecture:** Existing `ml.eval` harness and `ModelVersion` registry, extended only as necessary to preserve per-class segmentation/detection metrics and slice results.
- **Evaluation command:** `python -m ml.eval.predict_golden --dataset <golden-dataset> --weights <candidate.pt> --evaluate --out <predictions.json>` followed by `python -m ml.eval.report --golden <predictions.json> --out <accuracy-report.md>` and the existing gated `ml.registry.release.release(...)` flow.
- **Promotion metrics:** Enforce each phase's thresholds, quantity error <= 5%, repeatability, latency/resource budget, and no regression against the prior ACTIVE model.
- **Artifact:** Signed/checksummed immutable model, model card, dataset version, complete report, registry `ACTIVE` record, rollback pointer, and verified serving smoke result.
- **Integration:** The single existing production model-resolution and staging contract; do not introduce a second registry or untracked manual copy path.

### Frozen Swiss Dwellings training manifest

The full conversion contains 13,905 floor occurrences. Exactly 13,902 successfully rendered floors are eligible for training-manifest inclusion. Floors `5593`, `5639`, and `5640` remain excluded as `SOURCE_DATA_EXCEPTION`; each contains source `DOOR` geometry that intersects a `RAILING` but is more than 0.05 m from every source `WALL`. Their immutable source and canonical geometries are topologically equal, so no geometry correction or tolerance change is justified.

The versioned training manifest was frozen at `E:\Takeoff_datasets\swiss_dwellings\processed\full-v1\manifests\swiss_dwellings_training_manifest_v1.json` from the external SQLite ledger opened read-only and immutable. Its dataset version is `swiss-dwellings-takeoff-training-v1`, source dataset version is `3.0.0`, and conversion version is `swiss-dwellings-takeoff-full-v1`. The exact manifest SHA-256 is `6375b709932223b328de146282549807c4e2555526d4a2654ff216c68b377c4b`; the adjacent `.json.sha256` sidecar matches an independent SHA-256 calculation. A second freeze produced the identical hash.

The manifest contains all 13,902 successful rendered floors and no pending or failed floor. Eligible floor counts are train 11,337, validation 1,362, and test 1,203. Eligible-building counts represented in the manifest are train 2,596, validation 309, and test 278; the persisted assignment ledger remains train 2,597, validation 309, and test 278 because building `556::1261` contains only the three excluded floors. Every rendered input and room/separator/door/window label reference exists; missing references are zero. No excluded floor is eligible, duplicate relationships crossing splits are zero, and duplicate-connected building clusters crossing splits are zero.

The exclusions section records floors `5593`, `5639`, and `5640` as `SOURCE_DATA_EXCEPTION`, including their source hierarchy, exact recorded render errors, and maximum opening-to-wall distances of 0.108094315889646 m, 0.248831369511680 m, and 0.169990927256853 m respectively. The focused manifest/conversion validation suite passed 14/14 tests, covering deterministic freezing, completeness, exclusion reconciliation, path enforcement, leakage, and failure on a missing artifact.

**Swiss Dwellings frozen-dataset readiness: YES.** The 13,902-floor geometry-pretraining dataset is immutable by manifest and ready for an explicitly authorized training run; it remains unsuitable as the final customer-domain golden evaluation set.

### First Swiss Dwellings room-pretraining configuration

The room-only plan is frozen in `app/backend/ml/training/configs/swiss_dwellings_rooms_pretrain_v1.json` as `swiss-dwellings-rooms-yolov8m-seg-pretrain-v1`. It retains the proven Ultralytics YOLOv8m-seg family and initializes compatible backbone/neck parameters from the checksum-pinned `resplan-yolov8m-seg-12ep-640-v1` checkpoint. Because the Swiss model uses fourteen ordered classes instead of the deployed model's seven, its prediction head must be initialized for the new taxonomy; it is not valid to reuse or reinterpret the seven-class head.

The ordered training taxonomy is bedroom, bathroom, kitchen, living, living-dining, corridor, storage, balcony, office, utility, stairs, entry/lobby, generic room, and shaft. The exact source mappings and mask-ID 1–14 to training-ID 0–13 conversion are explicit in the configuration. Swiss semantics in `REVIEW`, `MAP_TO_OTHER`, or `IGNORE_FOR_CURRENT_MODEL` remain recoverable in metric provenance and are not painted into this model's supervision.

Planned hyperparameters are 1280-pixel input, batch 4, 100 epochs, AdamW with initial learning rate 0.001 and cosine decay to 1%, 3 warmup epochs, weight decay 0.0005, AMP, seed 42, deterministic mode, validation early-stopping patience 20, and checkpoints every 5 epochs. Monochrome-safe augmentation disables HSV, perspective, shear, mosaic, mixup, and copy/paste; it permits 2-degree scan skew, 2% translation, 10% scale, and horizontal/vertical flips. The measured train distribution ranges from 92 entry/lobby instances to 81,604 shafts, so the approved sampling plan is deterministic square-root inverse-frequency rare-class floor sampling capped at 0.5x–3x, no weight from duplicated source-row ownership, and at most 10% negative-only floors per batch.

The read-only preflight verified the exact manifest SHA-256, all 12,699 selected train/validation image-mask pairs, mask class IDs 0–14, all fourteen class IDs represented, three intentional negative masks with zero TRAIN room records, no unexpected empty mask, no excluded-floor inclusion, zero building/duplicate-cluster leakage, and the initialization checkpoint SHA-256. Focused configuration/training tests passed 20/20.

**YOLO start-readiness: NO.** The lossless Mask R-CNN path below supersedes the lossy YOLO polygon-label path for the first full-fidelity Swiss room experiment. Swiss-only validation remains geometry-pretraining evidence, never a claim of production accuracy; rights-cleared customer drawings and a customer-domain golden set are still required for promotion.

### Frozen full Mask R-CNN COCO-RLE adapter

The full adapter is frozen externally at `E:\\Takeoff_datasets\\swiss_dwellings\\processed\\full-v1\\mask-native\\rooms-maskrcnn-coco-rle-full-v1`. It uses canonical room WKT directly and writes one deterministic COCO uncompressed-RLE shard per floor, retaining interior holes exactly and recording every source instance and checksum. SQLite is the durable floor-level checkpoint; a rerun verifies completed files rather than rebuilding them.

Both complete adapter passes produced byte-identical manifest SHA-256 `61966eb947ba0ffc2dbc094c33142246b2be3a9cdba085c9f0cb36e93279ce29`. Pass 2 processed zero floors, wrote zero outputs, and found zero content/checksum mismatches. All 13,902 eligible floors reconcile: train 11,337, validation 1,362, test 1,203. All 495,835 authoritative room instances became 495,835 COCO-RLE annotations with zero rejection. The adapter preserves 7,669 hole-containing rooms and 9,841 interior rings, plus four intentional negative floors.

Every referenced image and annotation shard exists and matches its recorded hash. Excluded source-exception floors are absent. Building leakage, cross-split duplicate relationships, and duplicate-connected clusters crossing splits are all zero. This authorizes the isolated GPU/framework preflight only; it does not authorize model training or production promotion.

## Required next action

Run the isolated Mask R-CNN GPU/framework preflight against the frozen adapter, then seek explicit authorization before any training. In parallel, obtain the rights-cleared, project-split customer-domain room dataset and untouched golden set required for eventual production promotion.
