# Swiss Dwellings bounded preprocessing policy

This pipeline converts only a previously audited, complete-building sample of Swiss Dwellings v3.0.0. It must not be pointed at the full extracted corpus without a separate approval. Raw, extracted, sampled, and converted data stay outside Git.

## Grain and split rule

One output sample represents one complete `(site_id, building_id, plan_id, floor_id)` floor occurrence. All floors, units, repeated plans, derived labels, and future style variants for a `(site_id, building_id)` remain in one split. Exact or near-duplicate complete-floor fingerprints across buildings are unioned into one split cluster before assignment. Apartment-, unit-, page-, or row-level random splitting is prohibited.

## Taxonomy

`swiss_dwellings_taxonomy_v1.json` is authoritative for the pilot. It deliberately separates `living_dining` from `living`, keeps `generic_room` and `shaft` explicit, and excludes uncertain/specialty source labels instead of forcing them into the fourteen space classes. Excluded geometry is retained in metric provenance with an exclusion reason; it is not painted into a training mask.

Physical separators map to `wall`, `column`, and `railing`. `AREA_SPLITTER` is not a wall. Doors retain `door` versus `entrance_door`; windows retain source envelope/interior distinctions when present.

## Deduplication

Deduplication is strictly floor-local and semantic: rows collapse only when floor identity, entity type, source subtype, and normalized metric geometry are identical. This removes repeated unit ownership of one shared element without merging merely adjacent walls or differently typed coincident geometry. Every collapsed record retains all source CSV row numbers, unit IDs, apartment IDs, and area IDs.

## Rendering and labels

The pilot uses fixed `16 pixels_per_metre` and 2 m padding. Source extents are never stretched. Oversized plans fail clearly rather than being rescaled. Metadata stores the exact forward and inverse metric transform.

Each floor emits:

- deterministic RGB geometry render;
- semantic and 16-bit instance room masks;
- separator, door, and window semantic masks;
- YOLO-format door and window bounding boxes;
- metric WKT supervision and complete provenance in JSON;
- output hashes.

Drawing-like rasters produced from geometry are synthetic training inputs. They are suitable for geometry pretraining, not a substitute for customer construction sheets or the final golden set.

## Pilot acceptance checks

The validator rejects missing required IDs, unparseable/invalid/empty geometry, missing source provenance, output dimension mismatches, unknown mask values, transform round-trip error above half a pixel in metric units, opening labels farther than 5 cm from a wall, empty required label families, nondeterministic rerenders, or split leakage. Repeated/shared geometry removal and class distributions are reported rather than hidden.
