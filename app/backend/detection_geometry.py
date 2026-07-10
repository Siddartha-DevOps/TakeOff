"""
TakeOff.ai — Detection/Measurement geometry persistence
Closes the gap in memory/TOGAL_PARITY_REAUDIT.md ("PostGIS not live —
detections still saved as JSON in TakeoffResult"): every AI (or manual)
detection now also gets a real PostGIS Detection/Measurement row, not just
a JSON blob.

bbox -> WKT POLYGON uses the exact same [[x1,y1],[x2,y1],[x2,y2],[x1,y2]]
ring convention as frontend/src/annotations/geometry.js's rectFromBbox(),
so a Detection's geom and the frontend Annotation's geometry describe the
identical shape in the identical plan-space pixel coordinates.
"""

from typing import Optional

from geoalchemy2.elements import WKTElement
from sqlalchemy.orm import Session

import models

GEOM_SRID = 0  # plan-space pixels, not geographic — matches models.Detection.geom

_SYMBOL_DEFAULTS = {
    "doors": ("Door", "ea"),
    "windows": ("Window", "ea"),
    "mep": ("Fixture", "ea"),
}


def _bbox_to_wkt_polygon(bbox: list) -> WKTElement:
    x1, y1, x2, y2 = bbox
    ring = f"{x1} {y1}, {x2} {y1}, {x2} {y2}, {x1} {y2}, {x1} {y1}"
    return WKTElement(f"POLYGON(({ring}))", srid=GEOM_SRID)


def _points_to_wkt_linestring(points: list) -> WKTElement:
    coords = ", ".join(f"{x} {y}" for x, y in points)
    return WKTElement(f"LINESTRING({coords})", srid=GEOM_SRID)


def _symbol_bbox(item: dict) -> list:
    bbox = item.get("bbox")
    if bbox:
        return bbox
    x, y, width = item.get("x", 0), item.get("y", 0), item.get("width", 20)
    return [x - width / 2, y - 10, x + width / 2, y + 10]


def persist_detection_geometries(
    db: Session,
    project_id: int,
    drawing_id: int,
    detection: dict,
    source: str = "ai",
) -> int:
    """
    Write rooms/doors/windows/mep from a detection JSON payload (same shape
    as mock/mockAI.js's SAMPLE_DETECTION / ai/detection_engine.py output)
    into real Detection + Measurement rows with PostGIS geometry.

    Idempotent per call site is the caller's responsibility — this always
    inserts. Callers that re-run analysis on the same drawing should decide
    whether to supersede prior rows (out of scope here; see PR notes).

    Returns the number of Detection rows created.
    """
    created = 0

    for room in detection.get("rooms") or []:
        geom = _bbox_to_wkt_polygon(room["bbox"])
        det = models.Detection(
            project_id=project_id,
            drawing_id=drawing_id,
            annotation_id=str(room["id"]),
            annotation_type="area",
            class_label=room.get("label", "Room"),
            confidence=room.get("confidence"),
            source=source,
            geom=geom,
        )
        db.add(det)
        db.flush()  # need det.id for the Measurement FK
        db.add(models.Measurement(
            detection_id=det.id,
            value=room.get("area", 0),
            unit="sf",
            geom=geom,
        ))
        created += 1

    # Real vectorized wall centerlines (ai/wall_vectorization.py), typed
    # exterior/interior — LineString geometry, not a bbox rectangle, since a
    # wall segment has no meaningful footprint of its own to persist.
    for seg in detection.get("wall_segments") or []:
        geom = _points_to_wkt_linestring(seg["geometry"])
        det = models.Detection(
            project_id=project_id,
            drawing_id=drawing_id,
            annotation_id=str(seg["id"]),
            annotation_type="line",
            class_label=f"{seg.get('wall_type', 'interior')}_wall",
            confidence=seg.get("confidence"),
            source=source,
            geom=geom,
        )
        db.add(det)
        db.flush()
        db.add(models.Measurement(
            detection_id=det.id,
            value=seg.get("length_px", 0),
            unit="lf",
            geom=geom,
        ))
        created += 1

    for layer_key, (default_label, unit) in _SYMBOL_DEFAULTS.items():
        for item in detection.get(layer_key) or []:
            geom = _bbox_to_wkt_polygon(_symbol_bbox(item))
            det = models.Detection(
                project_id=project_id,
                drawing_id=drawing_id,
                annotation_id=str(item["id"]),
                annotation_type="count",
                class_label=item.get("type", default_label),
                confidence=item.get("confidence"),
                source=source,
                geom=geom,
            )
            db.add(det)
            db.flush()
            db.add(models.Measurement(
                detection_id=det.id,
                value=1,
                unit=unit,
                geom=geom,
            ))
            created += 1

    db.commit()
    return created
