# Swiss Dwellings taxonomy and deduplication review

Status: bounded-pilot policy review. This document does not authorize model training or full-corpus conversion.

## Mapping states

- `TRAIN`: current supervised TakeOff class.
- `MAP_TO_OTHER`: recoverable provenance-only AEC semantic outside the current model; not painted into current masks.
- `IGNORE_FOR_CURRENT_MODEL`: intentionally excluded from current masks but retained losslessly.
- `REVIEW`: candidate mapping requiring construction-domain approval.

The core training taxonomy remains unchanged. `other_aec` is not a new training class; it is a recoverable provenance bucket.

## Review of the 157 non-training area instances

| Original Swiss class | Candidate TakeOff class | State | Instances | Reason |
|---|---|---:|---:|---|
| ARCHIVE | storage | REVIEW | 1 | Storage-like, but not equivalent to general storage. |
| BASEMENT | — | IGNORE_FOR_CURRENT_MODEL | 4 | Floor/location descriptor, not a stable room function. |
| BASEMENT_COMPARTMENT | storage | REVIEW | 5 | Often storage, but use is not guaranteed. |
| CARPARK | other_aec | MAP_TO_OTHER | 2 | Useful parking space outside the current room taxonomy. |
| ELECTRICAL_SUPPLY | utility | REVIEW | 1 | Candidate building-services/utility space. |
| ELEVATOR | shaft | REVIEW | 98 | Vertical transport is not always equivalent to a shaft. |
| ELEVATOR_FACILITIES | utility | REVIEW | 1 | Candidate plant/utility space. |
| FACTORY_ROOM | other_aec | MAP_TO_OTHER | 1 | Industrial specialty room. |
| GARAGE | other_aec | MAP_TO_OTHER | 2 | Preserve for a future garage/parking model. |
| GARDEN | — | IGNORE_FOR_CURRENT_MODEL | 4 | Exterior landscape area. |
| HEATING | utility | REVIEW | 1 | Candidate building-services room. |
| LIGHTWELL | — | IGNORE_FOR_CURRENT_MODEL | 1 | Void/lightwell, not an occupied room. |
| MEETING_ROOM | office | REVIEW | 1 | Office-related, but not necessarily equivalent to office space. |
| OFFICE_TECH_ROOM | utility | REVIEW | 2 | Composite office/technical use. |
| OUTDOOR_VOID | — | IGNORE_FOR_CURRENT_MODEL | 1 | Exterior void. |
| PRAM_AND_BIKE_STORAGE_ROOM | storage | REVIEW | 2 | Specialty storage candidate. |
| SANITARY_ROOMS | bathroom | REVIEW | 8 | May include toilets/wash areas; not forced into bathroom. |
| SHELTER | generic_room | REVIEW | 4 | Specialty protected room needing domain policy. |
| TERRACE | balcony | REVIEW | 2 | Similar use but different enclosure/measurement rules. |
| TRANSPORT_SHAFT | shaft | REVIEW | 1 | Transport-specific vertical space. |
| VEHICLE_TRAFFIC_AREA | other_aec | MAP_TO_OTHER | 1 | Vehicle circulation outside the current room model. |
| VOID | — | IGNORE_FOR_CURRENT_MODEL | 14 | Non-room void retained only in provenance. |
| **Total** |  |  | **157** |  |

State totals: `REVIEW` 127, `MAP_TO_OTHER` 6, `IGNORE_FOR_CURRENT_MODEL` 24. Every record remains in `supervision.json` with source subtype, metric WKT, deterministic geometry ID, source rows, apartment/unit/area relationships, state, candidate mapping, and reason.

## Deduplication decision

The accepted key is floor identity + entity type + original subtype + normalized metric geometry. Exact repeated ownership rows collapse to one geometric training element. Differently typed coincident geometry and merely adjacent geometry do not collapse. The canonical record retains every contributing source row, unit, apartment, and area ID.

The bounded pilot reduced 22,904 rows to 19,515 canonical geometries. The 3,389 removed rows were represented by 2,905 shared canonical records; all 22,904 source-row relationships remain recoverable. Unique semantic geometry key loss was zero. Training weights must be based on canonical geometry, never the number of contributing source rows.

## Weighting recommendation

Do not apply weights before a training experiment. Start with one sample contribution per canonical geometry. Use class-balanced sampling or loss weights capped at 3× and derived from square-root inverse frequency, not raw inverse frequency. Preserve at least one negative floor batch per epoch but cap negative-only sampling near 10%. Repeated/shared geometry receives weight 1 regardless of how many units reference it. Evaluate rare-class recall separately and prefer targeted sampling over extreme loss weights.
