# Audit: A–D parity work + reconciliation status

Audit of the branch that built the A2→D6 roadmap
(`claude/compassionate-heisenberg-74yol1`) and the reconciliation started on
`claude/takeoff-integration-780vip`.

## Verdict
The A–D work is **real, wired, and compiles** — genuinely broad. But "done" was
overstated in four ways, all fixable: it was **not merged**, **not tested**, on a
**foundation divergent from PR #5's real detection engine**, and its **core AI
analysis was still a mock**.

## What was verified as genuinely wired ✅
- **All 18 new backend routers mounted** in `server.py`; MongoDB removed; backend
  byte-compiles.
- **Frontend builds** (2261 modules incl. three.js/OpenSeadragon) and calls real
  API clients (conditions, corrections, compare, chat, handoff, collab); chat
  hits real `chatAPI.send` with mock fallback.
- **Real PostGIS**: `Detection.geom`/`Measurement.geom` are geoalchemy2
  `Geometry(srid=0)`; pgvector `Vector(512)`; `CREATE EXTENSION postgis` baseline;
  9-migration Alembic chain is single-head/linear (valid).
- Per phase, all present and doing real work (honest degradation, not fake):
  A3 scale calibration, A4 assign-to-condition, A5 CorrectionEvent capture,
  A6 persistence, B1 conditions+formula, B2 chat, B3 pgvector+CLIP search,
  B4 compare, C2 tiling, C3 S3 presigned, C4 plan-set OCR, C5 eval,
  D1 PDF export+grouping, D2 UPC/WBS handoff, D3 **real WebSocket** collab,
  D4 RBAC+invites, D5 billing entitlements, D6 repeating groups + 3D.

## The four problems ❌
1. **Not integrated.** All A–D on one unmerged branch; `main` never moved. PR #5
   (real detection engine) also unmerged.
2. **Divergent foundations.** The A–D branch built its own PostGIS model + its own
   `alembic/`, off `main`, not off PR #5 — overlapping `models.py`, `server.py`,
   `Takeoff.jsx`, requirements, and migration dirs.
3. **~10.5k lines, zero new tests.** Only the 8 pre-existing detection tests.
4. **Core AI still mock.** `Takeoff.jsx` ran mock `runTakeoffAI` for the base
   analysis (the branch never got PR #5's real vector AUTODETECT), and `seed.py`
   had a syntax error (double-escaped docstring).

## Reconciliation done on this integration branch ✅
Took the A–D branch as the trunk (broader) and ported PR #5's real engine onto it:
- Added the self-contained, tested **`geometry/`** engine (units, vector_pdf,
  quantities, postgis bridge, **vector_symbol_match**) + **`ai/detect_symbols.py`**
  + `training/train_yolov8_seg.py` — all additive, no conflicts.
- Added **`POST /takeoff/drawings/{id}/autodetect`** (exact Area/Line/Count from
  vector geometry, no weights) and **`/detect_symbols`**, adapted to this branch's
  storage/entitlements; symbol counts folded into the TakeoffResult JSON (no schema
  change).
- Rewired **`Takeoff.jsx`** to call real AUTODETECT first and fall back to the mock
  only for non-vector sheets — so the core is no longer mock-first.
- Fixed **`seed.py`**. Ported the engine's tests.
- **41 backend tests pass** (33 engine + 8 existing); frontend builds.

## Remaining follow-ups (documented, not yet done)
1. **Coordinate-space transform for overlay/persistence.** The vector engine emits
   PDF points (72 DPI); this branch's canvas + `Detection.geom` use raster
   plan-space (300 DPI). The Area/Line/Count **numbers are correct** (computed in
   real feet), but AUTODETECT room polygons need ×(300/72) before they overlay/
   persist correctly in this branch's coordinate space. Until then, wire the
   numbers, not the on-canvas geometry, for vector results.
2. **Persist vector detections to PostGIS** via `persist_detection_geometries`
   (after the transform above), so vector AUTODETECT flows into
   Detection/Measurement, not just the JSON blob.
3. **Unify migrations** — the branch `alembic/` chain already covers PostGIS; drop
   PR #5's separate `migrations/` dir (superseded) once this branch is the trunk.
4. **Backfill tests** for the untested A–D routes (conditions, corrections,
   compare, export, handoff, realtime).
5. **Train raster weights** (GPU) and **stand up staging** (PostGIS, R2, Redis,
   Stripe/Liveblocks keys) to verify the service-dependent features and produce the
   eval number.

## Can't be verified in this environment
No GPU (raster weights), no live PostGIS/pgvector, no S3/Stripe/Liveblocks keys, no
runnable backend (fastapi/cv2 absent). All backend changes here are byte-compiled
and the pure engine is unit-tested; runtime behavior of service-dependent paths is
unproven until staging exists.
