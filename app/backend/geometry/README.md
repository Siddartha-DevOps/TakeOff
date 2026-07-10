# Accuracy Foundation — vector geometry + first-class PostGIS

This is the foundation for measurement accuracy (Togal-parity gaps **#26** and
**#27**). It has two halves.

## #26 — Vector-PDF geometry engine (the "98 %" lever)

The existing pipeline rasterizes every PDF to ~300 DPI and runs a CV model to
*re-detect* shapes. A vector PDF already contains every wall and room boundary
as exact coordinates — so we read and measure them directly instead.

- **`units.py`** — exact conversions. PDF user space is points (1/72 inch),
  fixed by the spec, so `points_to_feet` / `sqpoints_to_sqfeet` have **no DPI
  assumption**. The raster path must divide by an *assumed* scan DPI; if it's
  wrong, every measurement is wrong. This path can't be.
- **`vector_pdf.py`** — `extract_page_geometry()` pulls lines/rects/curves/text
  via PyMuPDF; `VectorPage.measure(scale_ratio)` builds room polygons with
  shapely and returns exact areas (sqft), perimeters and wall linear feet.
  `is_vector` cleanly separates vector sheets from scanned ones so the app can
  fall back to the AI/raster pipeline for the latter.
- **`postgis.py`** — converts engine output (shapely geometry) to EWKT /
  GeoJSON and to `Detection` / `Measurement` payloads.

`scale_ratio` = real-world inches per paper inch (matches `ai/scale_detection`):
`1/8"=1'-0"` → `96`.

### API

`GET /api/takeoff/drawings/{id}/vector-geometry?scale_ratio=96`

Returns rooms as GeoJSON polygons with exact areas + wall linear feet, or
`{"is_vector": false}` for raster sheets.

### One-click AUTODETECT (Togal parity)

`POST /api/takeoff/drawings/{id}/autodetect?scale_ratio=96`

The "Togal Button". Measures the real plan and returns the three takeoff
primitives explicitly:

```json
{
  "primitives": { "area": 512.0, "line": 192.0, "count": 4 },
  "page": { "width_pt": 1200, "height_pt": 800, "page_no": 0 },
  "area": [ { "id": "vr_0", "label": "Space", "sqft": 128.0, "geojson": {…} } ],
  "quantities": [ … ], "method": "vector", "status": "ok"
}
```

- **Area** = sqft, **Line** = linear ft, **Count** = each — Togal's three AI
  primitives (`geometry/quantities.py`). Result is persisted to `TakeoffResult`,
  so the Quantities panel and Excel export pick it up.
- `page` + per-space `geojson` (PDF points) let the frontend overlay detections
  **on the actual drawing** — the React `DetectionOverlay` multiplies point
  coordinates by the pdf.js render scale (both use a top-left, points origin).
  This replaces the old mock-on-a-fake-SVG rendering.

### Symbol counts (A1) — doors / windows / fixtures

`POST /api/takeoff/drawings/{id}/detect_symbols`

Togal's **Count** primitive for object types (not just spaces). Two paths:

- **Vector PDFs** (`geometry/vector_symbol_match.py`) — **no weights**. Parses
  each drawing path into a symbol candidate, computes a scale/rotation-invariant
  geometric signature (line/curve/rect fractions, aspect, complexity), clusters
  identical repeats by cosine similarity (KD-tree when SciPy is present), and
  classifies each cluster (door = leaf line + swing arc; window = thin rect;
  fixture = closed oval). Returns `symbol_counts` per type + per-instance
  geometry (GeoJSON) for overlay and persistence.
- **Raster/scanned** (`ai/detect_symbols.py`) — YOLOv8-seg over the rasterized
  page (18 classes). Returns `status: "needs_weights"` until
  `ai/models/symbol_counts/yolov8-seg.pt` exists (train with
  `training/train_yolov8_seg.py`).

Counts are also folded into `/autodetect`, saved to
`TakeoffResult.symbol_counts` (migration `0002`), and each instance is a
first-class `Detection` (`symbols_to_persistence`) linked to a `Sheet` — so
counts are editable through the CorrectionEvent loop.

### Weights (raster fallback)

The vector path needs **no model weights** — it's the highest-accuracy path and
works today. Scanned/raster sheets have no vector geometry, so they fall back to
the YOLOv8-seg detector (`ai/detection_engine.py`), which *does* need weights.
Until weights are present, AUTODETECT returns `status: "needs_weights"` rather
than fabricating numbers. To obtain weights:

- **Train:** `python training/train.py` on public floor-plan datasets
  (CubiCasa5K / RPLAN / Structured3D), then drop `rooms_doors_windows_v1.pt`
  into `ai/models/`.
- **Or auto-download:** set `AI_MODELS_BUCKET` to an S3 bucket holding
  `models/rooms_doors_windows_v1.pt` (see `_ensure_model`).

## #27 — Geometry as first-class data (PostGIS)

`../geo_models.py` defines the geometry-first model (CLAUDE.md guardrails #4/#5):
`Sheet`, `Condition`, `Detection`, `Measurement`, `CorrectionEvent`,
`ModelVersion`. `Detection.geom` / `Measurement.geom` are real PostGIS geometry
columns (GeoAlchemy2), **SRID 0** because drawing space is local planar CAD
coordinates, not lat/lon — PostGIS still does exact planar `ST_Area`/`ST_Length`.
This replaces storing detections as JSON `Text` blobs.

These tables live on a **separate metadata** and are created only by the Alembic
migration (which first enables PostGIS), so the app still boots on a database
where PostGIS isn't provisioned yet.

### Run the migration

```bash
cd app/backend
export DATABASE_URL=postgresql://user:pass@host/db   # must allow CREATE EXTENSION postgis
alembic upgrade head
# preview without a DB:
alembic upgrade head --sql
```

## Tests

```bash
cd app/backend && python -m pytest tests/ -q
```

Pure geometry — no GPU, weights, OCR, or database required. Synthetic
known-dimension PDFs assert measurements to a fraction of a unit.
