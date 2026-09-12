# CubiCasa5K evidence audit for TakeOff.ai

**Audit date:** 2026-09-01. No model was trained, no dataset was converted, and the raw archive was not modified or placed in Git.

## Identity and storage

The uploaded file is `E:\Takeoff_datasets\cubicasa5k.zip` (5,469,495,706 bytes). Its MD5 `0ce0b203d1e3c125b51087b219bd23b9` and size exactly match the official Zenodo record `10.5281/zenodo.2613548`. Its independently recorded SHA-256 is `a4a3398534d6abb7db7b8c6ca8877a6edf18897dcbd20f4582b3fdd3c46632a5`; a full ZIP CRC pass found no bad entry.

The original remains unchanged. The extracted read-only working copy is outside the repository at `E:\Takeoff_datasets\datasets\raw\cubicasa5k`. Processed and manifest directories were reserved at `E:\Takeoff_datasets\datasets\processed\cubicasa5k` and `E:\Takeoff_datasets\datasets\manifests\cubicasa5k`; no conversion output was created.

## Verified content

- 5,000 annotated plan folders and 5,000 `model.svg` files.
- 6,171 `F*_original.png` floor pages and 6,171 matching `F*_scaled.png` pages; 12,342 PNG files total.
- 17,345 files total and 1,032,432 SVG polygon elements.
- Categories: 3,732 `high_quality_architectural`, 992 `high_quality`, and 276 `colorful` plan folders.
- Image format: PNG only. Annotation format: SVG/XML groups containing polygons, paths, nested elements, and transforms.
- Official splits: 4,200 train / 400 validation / 400 test plan folders, representing 5,169 / 496 / 506 original floor pages. Split lists have no duplicate paths, direct path overlap, missing records, or unassigned plan folders.

## Taxonomy

The archive contains 32 `Space` labels. High-volume labels include `Undefined` 11,005; `Bedroom` 7,993; `Outdoor` 7,852; `Bath` 7,155; `Kitchen` 4,548; `Entry` 4,211; `LivingRoom` 3,958; `Closet` 2,695; `UserDefined` 1,856; `Room` 1,855; `Storage` 1,809; `DraughtLobby` 1,667; and `Utility` 1,015. The complete enumeration and counts are in `cubicasa5k_audit_manifest.json`.

Architectural geometry is extensive: 131,523 wall groups (80,196 unspecified/internal and 51,327 external), 49,945 door groups across eight subtype combinations, 44,009 windows across three subtypes, 4,632 stair groups, 15,663 railings, 11,942 columns, and 145,069 fixed-furniture groups across 66 enumerated classes. Fixtures include toilets, sinks, showers, tubs, cabinets, appliances, fireplaces, and sauna elements.

## Integrity findings

All PNGs opened and verified; all SVGs parsed. There are no empty files, missing original/scaled pairs, malformed SVGs, or corrupt PNGs. Two valid scaled images (`high_quality_architectural/13044/F1_scaled.png` and `F2_scaled.png`) are 14,304 × 6,316 pixels (90,344,064 pixels) and exceed Pillow's default decompression-bomb warning threshold; conversion must impose explicit resource limits rather than treating them as corrupt. Exact-content duplicates also exist:

- 2,063 duplicate PNG hash groups: 2,025 are within-plan pairs (commonly original/scaled copies), while 38 cross plan identities and affect 40 plans.
- 10 exact PNG duplicate groups cross official split boundaries.
- 16 duplicate SVG groups affect 32 plans; 6 groups affect 12 plans across official split boundaries.

Therefore the official split lists are structurally disjoint but not content-clean. Any research evaluation must remove/reassign content duplicates at the complete-plan level before measuring generalization.

## License and provenance decision

The uploaded ZIP itself contains no LICENSE, README, citation, or provenance document. Identity is established by its exact official Zenodo size/MD5 match. The official CubiCasa GitHub LICENSE says CC BY-NC 4.0, while Zenodo record metadata identifies CC BY-NC-SA 4.0. This conflict must be recorded, but both versions contain a NonCommercial restriction.

**Commercial TakeOff.ai model training: NO under the evidence currently available.** Do not train, merge into `spaces_v1`, redistribute, or publish derived weights for commercial use. A separate written commercial license from the rights holder would be required, followed by legal review of attribution, redistribution, derivative-data, and trained-weight terms.

## Suitability and required conversion

- **Rooms/spaces:** strong polygon-rich residential research source, but not representative real AEC construction sheets and not commercially usable. A reviewed mapping is mandatory.
- **Walls:** strong wall-polygon and external/internal supervision for research. Production conversion must preserve topology and SVG transforms, associate geometry with the correct floor page, and create wall masks/vector targets.
- **Doors/windows:** strong count/localization/geometry supervision for research. Conversion should produce reviewed detection boxes or masks from threshold polygons and optionally retain door swing paths/subtypes.
- **Other elements:** valuable research labels for stairs, railings, columns, fixtures, cabinets, appliances, plumbing objects, fireplaces, and sauna elements. Taxonomy must be reduced and normalized before any task-specific export.

The current converter is not production-safe for this archive: it chooses only `F1`, creates its own periodic train/validation split instead of preserving and de-duplicating official project splits, exports only mapped spaces, does not produce wall/door/window datasets, and does not resolve all nested SVG transforms. Full conversion was intentionally not run.

### Seven-class mapping risks

- Direct candidates: `LivingRoom→living`, `Bedroom→bedroom`, `Bath→bathroom`, `Kitchen→kitchen`, `Storage/Closet→storage` with policy review.
- Unsafe current mappings: `Room→living`, `Outdoor→balcony`, `Garage/Utility→storage`, `Sauna→bathroom`, and `Den→living` are semantically broad or domain-specific.
- CubiCasa exposes no `Balcony` space label in this archive; `Outdoor` cannot safely substitute for every balcony.
- CubiCasa exposes stairs as architectural object groups, not a `Space` room label, so the current space converter yields no reliable `stair` room supervision.
- `Undefined`, `UserDefined`, `Entry`, `DraughtLobby`, `Dining`, `Office`, `TechnicalRoom`, `Hall`, and other unsupported classes need explicit drop/ignore/taxonomy decisions rather than coercion.

## Next gate

Keep the source research-only. The single next action is to obtain written commercial training permission or a commercial license from the CubiCasa rights holder; if that cannot be obtained, exclude CubiCasa5K from TakeOff.ai production training and continue Task 6A with rights-cleared real AEC sheets.
