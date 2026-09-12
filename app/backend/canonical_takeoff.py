"""Canonical projections for user-corrected takeoff annotations.

``Drawing.annotations_data`` is the authoritative, versioned document.  This
module validates and remeasures that document on the server, then refreshes the
relational/PostGIS and legacy JSON projections consumed by 3D, search,
estimating, and exports.  The projections are deliberately rebuildable; they
are not a competing source of truth.
"""

from __future__ import annotations

import json
import math
from collections import OrderedDict
from typing import Any, Iterable

from geoalchemy2.elements import WKTElement

import models


GEOM_SRID = 0
TYPE_UNITS = {"area": "sf", "line": "lf", "count": "ea"}
LAYER_DEFAULTS = {
    "rooms": ("Flooring", "Room area"),
    "walls": ("Framing", "Wall linear footage"),
    "doors": ("Doors", "Door"),
    "windows": ("Windows", "Window"),
    "mep": ("MEP", "Fixture"),
}


class CanonicalAnnotationError(ValueError):
    """The annotation document cannot safely become canonical."""


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise CanonicalAnnotationError(f"{field} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise CanonicalAnnotationError(f"{field} must be a finite number") from None
    if not math.isfinite(result):
        raise CanonicalAnnotationError(f"{field} must be a finite number")
    return result


def _points(value: Any, field: str, minimum: int) -> list[list[float]]:
    if not isinstance(value, list) or len(value) < minimum:
        raise CanonicalAnnotationError(f"{field} requires at least {minimum} points")
    points: list[list[float]] = []
    for index, point in enumerate(value):
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise CanonicalAnnotationError(f"{field}[{index}] must be an [x, y] point")
        points.append([_number(point[0], f"{field}[{index}].x"), _number(point[1], f"{field}[{index}].y")])
    return points


def polygon_area(points: list[list[float]]) -> float:
    return abs(sum(
        points[index][0] * points[(index + 1) % len(points)][1]
        - points[(index + 1) % len(points)][0] * points[index][1]
        for index in range(len(points))
    )) / 2


def polyline_length(points: list[list[float]]) -> float:
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(points, points[1:]))


def arc_length(points: list[list[float]]) -> float:
    if len(points) != 3:
        return polyline_length(points)
    a, b, c = points
    denominator = 2 * (
        a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1])
    )
    if abs(denominator) < 1e-9:
        return polyline_length(points)
    aa, bb, cc = (p[0] ** 2 + p[1] ** 2 for p in (a, b, c))
    center = [
        (aa * (b[1] - c[1]) + bb * (c[1] - a[1]) + cc * (a[1] - b[1])) / denominator,
        (aa * (c[0] - b[0]) + bb * (a[0] - c[0]) + cc * (b[0] - a[0])) / denominator,
    ]
    angles = [math.atan2(p[1] - center[1], p[0] - center[0]) for p in (a, b, c)]
    normalize = lambda value: value % (2 * math.pi)
    ccw_total = normalize(angles[2] - angles[0])
    ccw_middle = normalize(angles[1] - angles[0])
    sweep = ccw_total if ccw_middle <= ccw_total else 2 * math.pi - ccw_total
    return math.hypot(a[0] - center[0], a[1] - center[1]) * sweep


def _feet_per_plan_unit(scale_ratio: Any, file_type: Any, scale_dpi: Any = None) -> float:
    ratio = _number(scale_ratio, "drawing.scale_ratio") if scale_ratio is not None else 0
    if ratio <= 0:
        raise CanonicalAnnotationError("A confirmed positive drawing scale is required for measurement")
    if str(file_type or "").upper() == "PDF":
        plan_units_per_inch = 72.0
    else:
        plan_units_per_inch = _number(scale_dpi, "drawing.scale_dpi") if scale_dpi is not None else 0
        if plan_units_per_inch <= 0:
            raise CanonicalAnnotationError(
                "Raster measurement requires known DPI or manual two-point calibration"
            )
    return ratio / (plan_units_per_inch * 12)


def normalize_annotations(
    annotations: Any, scale_ratio: Any = None, file_type: Any = "PDF", scale_dpi: Any = None
) -> list[dict]:
    """Validate and server-remeasure an annotation document."""
    if not isinstance(annotations, list):
        raise CanonicalAnnotationError("annotations must be a list")
    feet_per_unit = None
    seen: set[str] = set()
    normalized: list[dict] = []
    for index, raw in enumerate(annotations):
        if not isinstance(raw, dict):
            raise CanonicalAnnotationError(f"annotations[{index}] must be an object")
        annotation_id = str(raw.get("id") or "").strip()
        if not annotation_id or len(annotation_id) > 64 or annotation_id in seen:
            raise CanonicalAnnotationError(f"annotations[{index}].id is missing, duplicated, or too long")
        seen.add(annotation_id)
        annotation_type = raw.get("type")
        if annotation_type not in TYPE_UNITS:
            raise CanonicalAnnotationError(f"annotations[{index}].type is invalid")
        minimum = 3 if annotation_type == "area" else (2 if annotation_type == "line" else 1)
        geometry = _points(raw.get("geometry"), f"annotations[{index}].geometry", minimum)
        holes = []
        if annotation_type == "area":
            raw_holes = raw.get("holes") or []
            if not isinstance(raw_holes, list):
                raise CanonicalAnnotationError(f"annotations[{index}].holes must be a list")
            holes = [_points(ring, f"annotations[{index}].holes[{hole_index}]", 3)
                     for hole_index, ring in enumerate(raw_holes)]
        meta = raw.get("meta") or {}
        style = raw.get("style") or {}
        if not isinstance(meta, dict) or not isinstance(style, dict):
            raise CanonicalAnnotationError(f"annotations[{index}] meta/style must be objects")
        if annotation_type == "area":
            if feet_per_unit is None:
                feet_per_unit = _feet_per_plan_unit(scale_ratio, file_type, scale_dpi)
            plan_value = max(0.0, polygon_area(geometry) - sum(polygon_area(ring) for ring in holes))
            measured = plan_value * feet_per_unit ** 2
        elif annotation_type == "line":
            if feet_per_unit is None:
                feet_per_unit = _feet_per_plan_unit(scale_ratio, file_type, scale_dpi)
            plan_value = arc_length(geometry) if meta.get("curve") == "arc" else polyline_length(geometry)
            measured = plan_value * feet_per_unit
        else:
            measured = 1.0
        item = dict(raw)
        item.update({
            "id": annotation_id,
            "type": annotation_type,
            "geometry": geometry,
            "style": style,
            "layerId": str(raw.get("layerId") or "manual")[:64],
            "source": "ai" if raw.get("source") == "ai" else "manual",
            "meta": meta,
            "measuredValue": round(measured, 4),
        })
        if holes:
            item["holes"] = holes
        else:
            item.pop("holes", None)
        normalized.append(item)
    return normalized


def _condition_id(annotation: dict) -> int | None:
    value = annotation.get("meta", {}).get("conditionId")
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise CanonicalAnnotationError(f"Annotation {annotation['id']} has an invalid conditionId") from None


def validate_conditions(annotations: Iterable[dict], conditions: dict[int, Any]) -> None:
    for annotation in annotations:
        condition_id = _condition_id(annotation)
        if condition_id is None:
            continue
        condition = conditions.get(condition_id)
        if condition is None:
            raise CanonicalAnnotationError(
                f"Annotation {annotation['id']} references a condition outside this project"
            )
        expected_unit = TYPE_UNITS[annotation["type"]]
        if condition.annotation_type != annotation["type"] or condition.unit != expected_unit:
            raise CanonicalAnnotationError(
                f"Condition {condition_id} is not compatible with {annotation['type']} annotations"
            )


def _quantity_key(annotation: dict, conditions: dict[int, Any]) -> tuple[str, str, str]:
    condition_id = _condition_id(annotation)
    if condition_id is not None:
        condition = conditions[condition_id]
        return condition.trade, condition.name, condition.unit
    layer = annotation.get("layerId") or "manual"
    trade, default_item = LAYER_DEFAULTS.get(layer, ("Uncategorized", "Manual takeoff"))
    label = str(annotation.get("meta", {}).get("label") or default_item).strip() or default_item
    if annotation["type"] == "area" and "area" not in label.lower():
        label = f"{label} area"
    elif annotation["type"] == "line" and "linear" not in label.lower():
        label = f"{label} linear footage"
    return trade, label, TYPE_UNITS[annotation["type"]]


def build_quantities(annotations: Iterable[dict], conditions: dict[int, Any] | None = None) -> list[dict]:
    conditions = conditions or {}
    totals: OrderedDict[tuple[str, str, str], float] = OrderedDict()
    for annotation in annotations:
        if annotation.get("meta", {}).get("rejected"):
            continue
        key = _quantity_key(annotation, conditions)
        totals[key] = totals.get(key, 0.0) + float(annotation["measuredValue"])
    return [
        {"trade": trade, "item": item, "quantity": round(quantity, 4), "unit": unit}
        for (trade, item, unit), quantity in totals.items()
        if quantity > 0
    ]


def bounds_of(points: list[list[float]]) -> list[float]:
    return [min(p[0] for p in points), min(p[1] for p in points),
            max(p[0] for p in points), max(p[1] for p in points)]


def build_detection_projection(annotations: Iterable[dict], quantities: list[dict]) -> dict:
    projection = {"rooms": [], "doors": [], "windows": [], "mep": [], "wall_segments": []}
    active = [a for a in annotations if not a.get("meta", {}).get("rejected")]
    for annotation in active:
        meta = annotation.get("meta", {})
        label = str(meta.get("label") or "Takeoff")
        common = {
            "id": annotation["id"], "label": label, "geometry": annotation["geometry"],
            "condition_id": _condition_id(annotation), "source": annotation["source"],
        }
        if annotation["type"] == "area":
            projection["rooms"].append({
                **common, "bbox": bounds_of(annotation["geometry"]),
                "holes": annotation.get("holes", []), "area": annotation["measuredValue"],
                "confidence": meta.get("confidence"),
            })
        elif annotation["type"] == "line":
            projection["wall_segments"].append({
                **common, "wall_type": meta.get("wallType", "manual"),
                "length": annotation["measuredValue"], "curve": meta.get("curve"),
                "confidence": meta.get("confidence"),
            })
        else:
            layer = annotation.get("layerId")
            target = layer if layer in ("doors", "windows", "mep") else "mep"
            projection[target].append({
                **common, "type": label, "bbox": bounds_of(annotation["geometry"]),
                "confidence": meta.get("confidence"),
            })
    projection["quantities"] = quantities
    projection["summary"] = {
        "rooms": len(projection["rooms"]), "doors": len(projection["doors"]),
        "windows": len(projection["windows"]),
        "walls": len(projection["wall_segments"]),
        "totalArea": round(sum(a["measuredValue"] for a in active if a["type"] == "area"), 4),
    }
    return projection


def _ring_text(points: list[list[float]]) -> str:
    closed = points if points[0] == points[-1] else [*points, points[0]]
    return ", ".join(f"{point[0]} {point[1]}" for point in closed)


def geometry_element(annotation: dict) -> WKTElement:
    points = annotation["geometry"]
    if annotation["type"] == "area":
        rings = [_ring_text(points), *[_ring_text(ring) for ring in annotation.get("holes", [])]]
        return WKTElement(f"POLYGON({', '.join(f'({ring})' for ring in rings)})", srid=GEOM_SRID)
    if annotation["type"] == "line":
        coords = ", ".join(f"{point[0]} {point[1]}" for point in points)
        return WKTElement(f"LINESTRING({coords})", srid=GEOM_SRID)
    if len(points) >= 3:
        return WKTElement(f"POLYGON(({_ring_text(points)}))", srid=GEOM_SRID)
    x, y = points[0]
    epsilon = 1.0
    return WKTElement(
        f"POLYGON(({x-epsilon} {y-epsilon}, {x+epsilon} {y-epsilon}, "
        f"{x+epsilon} {y+epsilon}, {x-epsilon} {y+epsilon}, {x-epsilon} {y-epsilon}))",
        srid=GEOM_SRID,
    )


def canonical_quantities_for_drawing(db, drawing: models.Drawing) -> list[dict]:
    """Read quantities from annotations when present, with legacy fallback."""
    if drawing.annotations_data is not None:
        annotations = normalize_annotations(
            json.loads(drawing.annotations_data), drawing.scale_ratio, drawing.file_type,
            getattr(drawing, "scale_dpi", None),
        )
        condition_ids = {_condition_id(a) for a in annotations} - {None}
        conditions = {
            row.id: row for row in db.query(models.Condition).filter(
                models.Condition.project_id == drawing.project_id,
                models.Condition.id.in_(condition_ids),
            ).all()
        } if condition_ids else {}
        validate_conditions(annotations, conditions)
        return build_quantities(annotations, conditions)
    result = db.query(models.TakeoffResult).filter(
        models.TakeoffResult.drawing_id == drawing.id
    ).order_by(models.TakeoffResult.created_at.desc()).first()
    if not result or not result.quantities_data:
        return []
    try:
        quantities = json.loads(result.quantities_data)
    except (json.JSONDecodeError, TypeError):
        return []
    return quantities if isinstance(quantities, list) else []


def synchronize_corrected_takeoff(db, drawing: models.Drawing, annotations: Any) -> dict:
    """Refresh every local projection in the caller's transaction."""
    normalized = normalize_annotations(
        annotations, drawing.scale_ratio, drawing.file_type, getattr(drawing, "scale_dpi", None)
    )
    condition_ids = {_condition_id(a) for a in normalized} - {None}
    conditions = {
        row.id: row for row in db.query(models.Condition).filter(
            models.Condition.project_id == drawing.project_id,
            models.Condition.id.in_(condition_ids),
        ).all()
    } if condition_ids else {}
    validate_conditions(normalized, conditions)
    quantities = build_quantities(normalized, conditions)
    detection_projection = build_detection_projection(normalized, quantities)

    # Remove every prior projection, including rejected/deleted annotations.
    for detection in db.query(models.Detection).filter(
        models.Detection.drawing_id == drawing.id
    ).all():
        db.delete(detection)
    db.query(models.DrawingEmbedding).filter(
        models.DrawingEmbedding.drawing_id == drawing.id
    ).delete(synchronize_session=False)
    db.flush()

    active = [a for a in normalized if not a.get("meta", {}).get("rejected")]
    for annotation in active:
        geom = geometry_element(annotation)
        condition_id = _condition_id(annotation)
        detection = models.Detection(
            project_id=drawing.project_id,
            drawing_id=drawing.id,
            annotation_id=annotation["id"],
            annotation_type=annotation["type"],
            class_label=str(annotation.get("meta", {}).get("label") or "Takeoff")[:100],
            confidence=annotation.get("meta", {}).get("confidence"),
            source=annotation["source"],
            condition_id=condition_id,
            geom=geom,
        )
        db.add(detection)
        db.flush()
        db.add(models.Measurement(
            detection_id=detection.id,
            value=annotation["measuredValue"],
            unit=TYPE_UNITS[annotation["type"]],
            geom=geom,
        ))

    result = db.query(models.TakeoffResult).filter(
        models.TakeoffResult.drawing_id == drawing.id
    ).order_by(models.TakeoffResult.created_at.desc()).first()
    if result is None:
        result = models.TakeoffResult(
            drawing_id=drawing.id, confidence_scores="{}", processing_time_ms=0,
            ai_model_version="manual-corrected",
        )
        db.add(result)
    result.detection_data = json.dumps(detection_projection, separators=(",", ":"))
    result.quantities_data = json.dumps(quantities, separators=(",", ":"))

    return {
        "annotations": normalized,
        "quantities": quantities,
        "detection": detection_projection,
        "active_count": len(active),
    }
