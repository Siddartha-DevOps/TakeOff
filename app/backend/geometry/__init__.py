"""
TakeOff.ai — Geometry engine.

This package is the "accuracy foundation". It has two jobs:

1. Measure *real vector geometry* directly from vector PDFs (the "98 %" lever).
   Vector PDFs store every line, rectangle and curve as exact coordinates in
   PDF points (1/72 inch). Reading those coordinates and scaling them is exact
   and resolution-independent — unlike the raster pipeline, which rasterizes to
   an assumed DPI and then has a CV model re-detect shapes that were already
   present, exactly, in the file. See `vector_pdf.py`.

2. Treat geometry as first-class data. The engine emits shapely geometries that
   convert cleanly to PostGIS (EWKT / GeoJSON) so detections and measurements
   are stored as real geometry, not JSON blobs. See `postgis.py`.

Nothing in this package requires a GPU, model weights, OCR, or a database — it
is pure geometry, so it is fast and exhaustively testable.
"""

from .units import (
    POINTS_PER_INCH,
    INCHES_PER_FOOT,
    points_to_feet,
    points_to_real_inches,
    sqpoints_to_sqfeet,
)
from .vector_pdf import (
    VectorPage,
    Segment,
    extract_page_geometry,
    is_vector_pdf_page,
    measure_pdf,
)
from .quantities import autodetect_from_measure, vector_quantities
from .vector_symbol_match import match_symbols, symbols_to_persistence

__all__ = [
    "POINTS_PER_INCH",
    "INCHES_PER_FOOT",
    "points_to_feet",
    "points_to_real_inches",
    "sqpoints_to_sqfeet",
    "VectorPage",
    "Segment",
    "extract_page_geometry",
    "is_vector_pdf_page",
    "measure_pdf",
    "autodetect_from_measure",
    "vector_quantities",
    "match_symbols",
    "symbols_to_persistence",
]
