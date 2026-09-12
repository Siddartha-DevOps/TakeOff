# First-batch sampling plan — 60 in-domain sheets

The target is exactly 60 sheets, within the approved 50–75 range. All quotas are project-aware: related pages, revisions, and units stay together. Do not fill a quota with unapproved data. Hospitality may be unavailable; any substitution requires a documented manifest-version change, never an unrecorded convenience swap.

## Primary building type (mutually exclusive; total 60)

| Drawing type | Sheets |
|---|---:|
| Residential single-family | 15 |
| Apartment/multi-unit | 15 |
| Commercial/retail | 10 |
| Office | 10 |
| Hospitality | 10 |

## Source-format slice (mutually exclusive; total 60)

| Source format | Sheets |
|---|---:|
| Clean vector PDF | 36 |
| Scanned raster plan | 18 |
| Native raster image/export | 6 |

## Complexity slice (mutually exclusive; total 60)

| Complexity | Sheets |
|---|---:|
| Simple/sparse plan | 20 |
| Dense/text-heavy or highly partitioned plan | 30 |
| Mixed/moderate | 10 |

At least 30 sheets must come from genuine multi-page plan sets. Seek multiple independent source organizations and projects so a future project-level validation/golden holdout remains possible. Prefer architectural floor plans; non-floor-plan disciplines are intake negatives and do not replace the 60 target sheets.

## Minimum labeled-instance coverage before accepting batch v1

| Class | Minimum instances |
|---|---:|
| `living` | 40 |
| `bedroom` | 90 |
| `bathroom` | 70 |
| `kitchen` | 40 |
| `balcony` | 15 |
| `stair` | 15 |
| `storage` | 25 |

These are first-batch floors, not full-dataset promotion support. Sampling should deliberately seek stairs, balconies, and storage rather than hope they appear. Also seek at least five sheets for each difficult-case tag defined in the main configuration where feasible.

## Taxonomy-gap flags

Count, but do not force-label: corridors/hallways, dining, offices/studies, lobbies, laundry, mechanical/electrical/utility rooms, elevators, shafts, garages, porches/decks/patios, and ambiguous generic rooms. Record `unmapped_*` review metadata. If any excluded concept appears on at least 20% of accepted sheets or is operationally critical, raise a taxonomy decision before full annotation—not during training.
