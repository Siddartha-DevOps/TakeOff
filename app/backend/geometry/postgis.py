"""
Bridge: shapely geometry  ->  PostGIS-ready values.

The geometry engine emits shapely geometries in a local planar coordinate
system (PDF points), so we store them with SRID 0 — they are CAD-style drawing
coordinates, not geographic lat/lon. PostGIS computes planar length/area on
SRID 0 geometry without any projection, which is exactly what a floor plan
needs.

These helpers turn engine output into the values that go onto the first-class
``Detection`` / ``Measurement`` rows (see ``geo_models.py``): EWKT for the
geometry column, plus GeoJSON for shipping geometry to the canvas. No database
or GeoAlchemy2 import is required here, so this is pure and fully testable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .units import points_to_feet, sqpoints_to_sqfeet

if TYPE_CHECKING:  # pragma: no cover - typing only
    from shapely.geometry.base import BaseGeometry

#: Local planar (non-geographic) reference. Drawing units = PDF points.
DRAWING_SRID = 0


def to_ewkt(geom: "BaseGeometry", srid: int = DRAWING_SRID) -> str:
    """Serialize a shapely geometry to EWKT (``SRID=n;WKT``) for PostGIS."""
    return f"SRID={srid};{geom.wkt}"


def to_geojson(geom: "BaseGeometry") -> dict[str, Any]:
    """Serialize a shapely geometry to a GeoJSON geometry dict (for the canvas)."""
    from shapely.geometry import mapping

    return mapping(geom)


def polygon_from_points(points: list[tuple[float, float]]):
    """Build a shapely Polygon from an ordered ring of (x, y) points."""
    from shapely.geometry import Polygon

    return Polygon(points)


def measurement_from_polygon(
    geom: "BaseGeometry",
    scale_ratio: float,
) -> dict[str, Any]:
    """Area + perimeter measurement payload for a polygon geometry.

    Returns the fields needed to create both a ``Measurement`` (area, sqft) and
    optionally a derived linear measurement (perimeter, ft), each with the same
    geometry. Values are exact for vector geometry.
    """
    return {
        "area": {
            "value": round(sqpoints_to_sqfeet(geom.area, scale_ratio), 2),
            "unit": "sqft",
        },
        "perimeter": {
            "value": round(points_to_feet(geom.length, scale_ratio), 2),
            "unit": "ft",
        },
    }


def detection_payload(
    geom: "BaseGeometry",
    detection_class: str,
    *,
    confidence: float = 1.0,
    source: str = "vector",
    srid: int = DRAWING_SRID,
) -> dict[str, Any]:
    """Assemble kwargs for a first-class ``Detection`` row from a geometry.

    ``source`` records provenance — ``"vector"`` (exact PDF geometry),
    ``"ai"`` (model prediction) or ``"manual"`` (user-drawn) — so accuracy and
    the correction flywheel can be reasoned about per origin.
    """
    return {
        "detection_class": detection_class,
        "confidence": confidence,
        "source": source,
        "geom_ewkt": to_ewkt(geom, srid),
        "geojson": to_geojson(geom),
    }


def rooms_to_persistence(
    measurement: dict[str, Any],
    scale_ratio: float,
) -> list[dict[str, Any]]:
    """Turn ``VectorPage.measure()`` output into per-room persistence records.

    Each record bundles the ``Detection`` payload and its area/perimeter
    ``Measurement`` payloads, ready to write to the PostGIS-backed tables.
    """
    records: list[dict[str, Any]] = []
    for room in measurement.get("rooms", []):
        geom = room.get("geometry")
        if geom is None:
            continue
        records.append(
            {
                "detection": detection_payload(
                    geom,
                    detection_class=room.get("label", "Space"),
                    confidence=room.get("confidence", 1.0),
                    source="vector",
                ),
                "measurements": measurement_from_polygon(geom, scale_ratio),
                "ref_id": room.get("id"),
            }
        )
    return records
