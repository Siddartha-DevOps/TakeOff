# Human annotation handoff — in-domain spaces v1

## Package contents and order

1. Read `IN_DOMAIN_SPACES_ANNOTATION_GUIDELINES.md` completely.
2. Confirm the batch intake report marks every assigned derivative eligible; never annotate restricted originals.
3. Use the immutable class order: living, bedroom, bathroom, kitchen, balcony, stair, storage.
4. Produce one YOLO segmentation polygon row per room instance, normalized to the derivative image dimensions.
5. Return labels, annotator/reviewer IDs, difficult-case tags, exclusions, ambiguity notes, and the exact derivative SHA-256.

## Polygon rules

- Trace the visible usable floor-area boundary at the inside face of walls.
- Use at least three points; keep all points normalized and within the page.
- Do not include wall thickness, door swings, fixtures, text, or dimension graphics.
- Do not self-intersect, duplicate vertices unnecessarily, or overlap adjacent room masks.
- Label each room instance separately on multi-unit plans.
- For cropped rooms, trace only visible defensible geometry and add `partial_room` plus `crop_boundary`.
- Do not create a polygon when class or boundary is speculative.

## Ambiguous cases

- Open living/kitchen: split only at a drawn or consistently defined functional boundary; otherwise record an exclusion.
- Corridor/shaft/elevator/office/dining/utility: record an `unmapped_*` exclusion; never force into a target class.
- Storage: room-scale enclosed storage/closets only, not cabinetry.
- Stair: one bounded footprint, not individual treads; omit elevator/void geometry.
- Balcony: usable bounded balcony/loggia only; flag terrace/porch/deck ambiguity.
- Low-quality scan: reject the instance/sheet if reviewers cannot reproduce the boundary consistently.

## Reviewer checklist

- [ ] Label file hash corresponds to the assigned derivative hash.
- [ ] Every visible target room is labeled exactly once or has an explicit exclusion reason.
- [ ] Class IDs match the frozen seven-class order.
- [ ] Polygons follow inside-wall floor boundaries and preserve crop rules.
- [ ] No self-intersection, zero area, material overlap, or out-of-range coordinates.
- [ ] Open-plan, partial, crop, scan, text-heavy, multi-unit, stair, balcony, and storage cases are tagged.
- [ ] Unsupported room types are excluded rather than coerced.
- [ ] Annotator and independent reviewer identities are recorded.
- [ ] Golden candidates received second review but were not used for guidance/tuning.

## Acceptance criteria

A sheet is accepted only after intake eligibility, complete labels or approved-negative status, independent review, zero critical QA errors, resolved duplicate/leakage findings, and validator success. Any correction after acceptance creates a new dataset version and review record; golden labels are never silently edited.
