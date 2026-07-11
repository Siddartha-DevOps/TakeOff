"""
Coordinate-space conversion between the vector engine and this app's canonical
plan-space.

The vector engine works in **PDF points** (1/72"): that's what PyMuPDF's
`get_drawings()` returns and what the PDF canvas (react-pdf / pdf.js, via
`pageNativeSize`) uses for on-screen mapping — so vector-AUTODETECT geometry
overlays the PDF canvas directly, no conversion.

Persistence is different. `models.Detection.geom`, `scale_ratio`, the AI/YOLO
detections, and the 3D view (`Drawing3DView.jsx`) all live in **300-DPI raster
plan-space pixels** — the space `ai/preprocessing.py` rasterizes PDFs into and
`routes/scale_routes.py` calibrates against (`REFERENCE_DPI = 300`). To store a
vector detection alongside those consistently, its point coordinates must be
scaled by 300/72 first. This module is that one conversion, matching the
`plan_pixel_distance * (REFERENCE_DPI / PDF_POINTS_PER_INCH)` step in
`scale_routes.calibrate_scale`.

Real-world quantities (sqft/ft) are DPI-independent and are NOT touched here —
they're already correct from the engine regardless of pixel scale.
"""

from __future__ import annotations

from .units import POINTS_PER_INCH  # 72.0

#: Raster DPI the persisted plan-space + scale_ratio are defined against.
REFERENCE_DPI: float = 300.0

#: Multiply a PDF-point coordinate by this to reach 300-DPI raster pixels.
PX_PER_POINT: float = REFERENCE_DPI / POINTS_PER_INCH  # 4.1666…


def points_to_pixels(value: float, dpi: float = REFERENCE_DPI) -> float:
    """Scale a single PDF-point coordinate to raster pixels at `dpi`."""
    return value * (dpi / POINTS_PER_INCH)


def bbox_to_pixels(bbox, dpi: float = REFERENCE_DPI) -> list[float]:
    """Scale a [x1, y1, x2, y2] bbox from PDF points to raster pixels."""
    return [round(points_to_pixels(v, dpi), 2) for v in bbox]


def ring_to_pixels(ring, dpi: float = REFERENCE_DPI) -> list[list[float]]:
    """Scale a polygon/polyline ring [[x, y], ...] from points to pixels."""
    return [[round(points_to_pixels(x, dpi), 2), round(points_to_pixels(y, dpi), 2)] for x, y in ring]
