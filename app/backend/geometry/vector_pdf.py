"""
Vector-PDF geometry engine — measure real geometry, don't re-detect it.

A vector PDF already contains every wall, room boundary and fixture outline as
exact coordinates. The raster pipeline throws that away (rasterize → CV detect →
guess scale → convert pixels). This module reads the geometry straight out of
the file with PyMuPDF and measures it in exact real-world units.

Pipeline:
    extract_page_geometry(pdf) -> VectorPage      # primitives in PDF points
    VectorPage.room_polygons()  -> [shapely.Polygon]  # closed faces (rooms)
    VectorPage.measure(scale)   -> dict           # rooms + walls in ft / sqft

Output geometries are shapely objects in PDF-point coordinates (SRID 0, planar).
They convert directly to PostGIS via ``geometry.postgis`` — that is what makes
detections first-class geometry instead of JSON blobs.

PyMuPDF (``fitz``) is imported lazily so the module is importable on web workers
that only need the dataclasses / type hints.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from .units import points_to_feet, sqpoints_to_sqfeet

if TYPE_CHECKING:  # pragma: no cover - typing only
    from shapely.geometry import Polygon

Point = tuple[float, float]
Segment = tuple[Point, Point]

# A page needs at least this many real vector segments before we trust the
# vector path. Scanned/raster PDFs carry a single full-page image and ~0 vector
# segments, so this cleanly separates "vector" from "raster" sheets.
MIN_VECTOR_SEGMENTS = 12

# Bezier curves are sampled into this many straight chords for length and
# polygon building. 8 keeps perimeter error well under 0.1% for typical arcs.
BEZIER_SAMPLES = 8


@dataclass
class VectorPage:
    """Vector primitives extracted from one PDF page, in PDF points.

    Coordinates use PyMuPDF page space (top-left origin, y increasing
    downward), the same space used for text words, so geometry and labels line
    up without any transform.
    """

    page_no: int
    width_pt: float
    height_pt: float
    segments: list[Segment] = field(default_factory=list)
    rectangles: list[tuple[float, float, float, float]] = field(default_factory=list)
    words: list[tuple[float, float, float, float, str]] = field(default_factory=list)

    @property
    def is_vector(self) -> bool:
        """True when the page carries enough real vector linework to measure."""
        return len(self.segments) >= MIN_VECTOR_SEGMENTS

    # ── measurement ────────────────────────────────────────────────
    def total_line_length_pt(self) -> float:
        """Sum of all segment lengths in PDF points (raw wall-ish linework)."""
        total = 0.0
        for (x1, y1), (x2, y2) in self.segments:
            total += ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
        return total

    def wall_linear_feet(self, scale_ratio: float) -> float:
        """Total linework length converted to real-world linear feet."""
        return points_to_feet(self.total_line_length_pt(), scale_ratio)

    def room_polygons(self, min_area_pt: float = 1.0) -> list["Polygon"]:
        """Build closed polygons (candidate rooms) from the linework.

        Uses shapely's ``polygonize`` over the noded union of every segment, so
        any set of lines that encloses an area becomes a polygon — exactly how a
        floor plan's walls bound rooms. Polygons smaller than ``min_area_pt``
        (square points) are dropped as noise.
        """
        from shapely.geometry import LineString
        from shapely.ops import polygonize, unary_union

        lines = [
            LineString([a, b])
            for a, b in self.segments
            if a != b
        ]
        if not lines:
            return []

        noded = unary_union(lines)
        polys = [p for p in polygonize(noded) if p.area >= min_area_pt]
        # Largest first — the dominant faces are the real rooms.
        polys.sort(key=lambda p: p.area, reverse=True)
        return polys

    def measure(
        self,
        scale_ratio: float,
        min_room_sqft: float = 10.0,
    ) -> dict:
        """Measure rooms and walls in exact real-world units.

        Returns a dict shaped like the raster detector's output (so the rest of
        the app can consume it unchanged) plus the underlying shapely geometry
        for first-class persistence.
        """
        polys = self.room_polygons()

        rooms: list[dict] = []
        for i, poly in enumerate(polys):
            area_sqft = sqpoints_to_sqfeet(poly.area, scale_ratio)
            if area_sqft < min_room_sqft:
                continue
            perimeter_ft = points_to_feet(poly.length, scale_ratio)
            cx, cy = poly.centroid.x, poly.centroid.y
            minx, miny, maxx, maxy = poly.bounds
            rooms.append(
                {
                    "id": f"vr_{i}",
                    "label": "Space",  # vector geometry is unlabeled; HITL/AI classifies
                    "area": round(area_sqft, 1),
                    "perimeter_ft": round(perimeter_ft, 1),
                    "bbox": [round(minx), round(miny), round(maxx), round(maxy)],
                    "centroid": [round(cx, 2), round(cy, 2)],
                    "confidence": 1.0,  # exact geometry, not a prediction
                    "geometry": poly,  # shapely Polygon in PDF points (SRID 0)
                }
            )

        wall_lf = round(self.wall_linear_feet(scale_ratio), 1)
        total_area = round(sum(r["area"] for r in rooms), 1)

        return {
            "method": "vector",
            "is_vector": self.is_vector,
            "scale_ratio": scale_ratio,
            "page_no": self.page_no,
            "rooms": rooms,
            "summary": {
                "rooms": len(rooms),
                "walls_lf": wall_lf,
                "totalArea": total_area,
            },
            # Geometry is exact, so we can say so honestly instead of guessing a
            # confidence (the raster path cannot).
            "accuracy_note": (
                "Measured from native PDF vector geometry; lengths/areas are "
                "exact for the drawn linework and independent of render DPI."
            ),
        }


# ──────────────────────────────────────────────────────────────
# Extraction
# ──────────────────────────────────────────────────────────────
def _bezier_points(p0: Point, p1: Point, p2: Point, p3: Point, n: int) -> list[Point]:
    """Sample a cubic bezier into ``n`` chord endpoints (inclusive of ends)."""
    pts: list[Point] = []
    for i in range(n + 1):
        t = i / n
        mt = 1 - t
        x = (
            mt ** 3 * p0[0]
            + 3 * mt ** 2 * t * p1[0]
            + 3 * mt * t ** 2 * p2[0]
            + t ** 3 * p3[0]
        )
        y = (
            mt ** 3 * p0[1]
            + 3 * mt ** 2 * t * p1[1]
            + 3 * mt * t ** 2 * p2[1]
            + t ** 3 * p3[1]
        )
        pts.append((x, y))
    return pts


def _rect_segments(x0: float, y0: float, x1: float, y1: float) -> list[Segment]:
    """Four edges of an axis-aligned rectangle as segments."""
    return [
        ((x0, y0), (x1, y0)),
        ((x1, y0), (x1, y1)),
        ((x1, y1), (x0, y1)),
        ((x0, y1), (x0, y0)),
    ]


def extract_page_geometry(pdf_path: str | Path, page_no: int = 0) -> VectorPage:
    """Extract vector primitives and text words from one PDF page.

    Reads line/rect/curve drawing items via ``page.get_drawings()`` and text via
    ``page.get_text("words")``. All coordinates stay in PDF points.
    """
    import fitz  # lazy: heavy native dep

    doc = fitz.open(str(pdf_path))
    try:
        page = doc[page_no]
        rect = page.rect
        vp = VectorPage(
            page_no=page_no,
            width_pt=float(rect.width),
            height_pt=float(rect.height),
        )

        for path in page.get_drawings():
            for item in path.get("items", []):
                op = item[0]
                if op == "l":  # line: (p1, p2)
                    p1, p2 = item[1], item[2]
                    vp.segments.append(((p1.x, p1.y), (p2.x, p2.y)))
                elif op == "re":  # rectangle
                    r = item[1]
                    vp.rectangles.append((r.x0, r.y0, r.x1, r.y1))
                    vp.segments.extend(_rect_segments(r.x0, r.y0, r.x1, r.y1))
                elif op == "qu":  # quad — four corners
                    q = item[1]
                    corners = [
                        (q.ul.x, q.ul.y),
                        (q.ur.x, q.ur.y),
                        (q.lr.x, q.lr.y),
                        (q.ll.x, q.ll.y),
                    ]
                    for a, b in zip(corners, corners[1:] + corners[:1]):
                        vp.segments.append((a, b))
                elif op == "c":  # cubic bezier: (p1, p2, p3, p4)
                    p0, p1, p2, p3 = item[1], item[2], item[3], item[4]
                    samples = _bezier_points(
                        (p0.x, p0.y), (p1.x, p1.y), (p2.x, p2.y), (p3.x, p3.y),
                        BEZIER_SAMPLES,
                    )
                    for a, b in zip(samples, samples[1:]):
                        vp.segments.append((a, b))

        for w in page.get_text("words"):
            x0, y0, x1, y1, text = w[0], w[1], w[2], w[3], w[4]
            vp.words.append((x0, y0, x1, y1, text))

        return vp
    finally:
        doc.close()


def is_vector_pdf_page(pdf_path: str | Path, page_no: int = 0) -> bool:
    """Cheap check: does this page have enough vector linework to measure?

    Lets the analyze pipeline route vector PDFs to the exact engine and fall
    back to the raster/CV pipeline for scanned sheets.
    """
    return extract_page_geometry(pdf_path, page_no).is_vector


def measure_pdf(
    pdf_path: str | Path,
    scale_ratio: float,
    page_no: int = 0,
    min_room_sqft: float = 10.0,
) -> Optional[dict]:
    """One-call helper: extract + measure a page.

    Returns the measurement dict, or ``None`` if the page is not vector (caller
    should fall back to the raster pipeline).
    """
    vp = extract_page_geometry(pdf_path, page_no)
    if not vp.is_vector:
        return None
    return vp.measure(scale_ratio, min_room_sqft=min_room_sqft)
