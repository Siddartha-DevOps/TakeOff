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
