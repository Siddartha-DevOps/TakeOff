# In-domain room/space annotation policy

## Scope and evidence

This policy governs the first production fine-tuning corpus for the existing seven-class YOLO segmentation model. A sheet may enter the corpus only when its manifest contains an auditable right to use it for commercial model training. Possession, a public URL, or a converter is not permission. Customer material must be covered by explicit consent/data terms and must be de-identified before annotation.

Annotate the visible floor-area footprint of each enclosed or clearly delimited target space as one simple polygon. Trace the inside face of bounding walls where readable. Do not include wall thickness, door swings, fixtures, text, or dimension strings. Keep polygons within the image. A cropped room is labeled only when its visible boundary and semantic class are sufficiently clear, and it must receive the `crop_boundary` and `partial_room` difficulty tags.

## Canonical seven classes

| ID | Class | Include | Exclude / ambiguity rule |
|---:|---|---|---|
| 0 | `living` | Living rooms, lounges, family/great rooms when the living function is explicit | Dining-only rooms, corridors, lobbies, offices. In open plans, use the drawn boundary; if no defensible boundary exists, mark the region `unmapped_open_plan` in review metadata rather than invent one. |
| 1 | `bedroom` | Bedrooms and sleeping rooms explicitly identified or unambiguous from plan context | Studies/offices and unlabeled generic rooms unless a reviewer can establish bedroom use. |
| 2 | `bathroom` | Bathrooms, WCs/toilet rooms, shower rooms and ensuites | Laundry, janitor, plumbing shafts. Record the source subtype in metadata. |
| 3 | `kitchen` | Kitchens, kitchenettes and pantry areas that are part of a clearly bounded kitchen footprint | Dining-only areas. In open living/kitchen plans, split only at a drawn boundary or consistently documented functional boundary. |
| 4 | `balcony` | Usable balconies/loggias/terraces clearly associated with the floor plan | Porches, decks, patios and roofs unless taxonomy review explicitly approves a mapping. |
| 5 | `stair` | The floor footprint of a stair enclosure or clearly bounded stair zone on that sheet | Elevators, ramps and shafts. Do not trace individual treads as separate instances. |
| 6 | `storage` | Enclosed storage rooms, closets, wardrobes and pantries used primarily for storage | Mechanical/electrical rooms, shafts and ambiguous service voids. Tiny built-in cabinets are not room instances. |

## Known domain mismatch

ResPlan semantics do not fully represent real AEC sheets. The seven-class model has no corridor/hallway, dining, office/study, lobby, laundry, utility/mechanical/electrical, elevator, shaft, garage, porch/deck/patio, or generic `other` class. Annotators must not force these regions into a nearby class. Record them as reviewed exclusions with an `unmapped_*` reason. Before expanding the taxonomy, measure their frequency in the intake corpus; changing classes is a separate model decision.

## Difficult-case policy

- **Open-plan living/kitchen:** label separate polygons only with a defensible drawn or consistently documented functional boundary; otherwise exclude the ambiguous zone and flag `open_plan`.
- **Partial rooms/crop boundaries:** label only the visible interior if class and boundary are clear; never infer geometry outside the crop.
- **Corridors and shafts:** reviewed negative/excluded regions, never `living` or `storage` by convenience.
- **Closets/storage:** label enclosed walk-in and room-scale storage; omit cabinetry. Keep a subtype note for later taxonomy analysis.
- **Stairs:** one footprint per bounded stair zone per sheet; exclude voids and elevators.
- **Balconies:** include only the usable bounded area and flag ambiguous exterior-space terminology.
- **Text-heavy drawings:** polygons follow geometry, not OCR boxes; flag occluded or illegible boundaries.
- **Low-quality scans:** label only where the boundary can be placed consistently; otherwise reject the sheet from supervised data.
- **Multi-unit plans:** each room is an instance; retain unit/project IDs in metadata so all units and revisions from one project stay in one split.

## Review and acceptance

Every sheet requires a primary annotator and independent reviewer. Golden sheets require a second reviewer, `golden_approved=true`, and `untouched=true`. The golden set is frozen before any fine-tuning or threshold selection. Corrections discovered while evaluating golden data produce a new version; they are never silently edited in place.

Reject or return a sheet when polygons self-intersect, target rooms are missing, masks overlap materially, the image is corrupt/too small, rights evidence is absent, or class intent cannot be resolved. Negative sheets must be explicitly marked `negative=true`; an accidentally empty label file is not a negative example.
