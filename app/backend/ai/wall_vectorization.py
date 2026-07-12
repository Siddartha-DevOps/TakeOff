"""
TakeOff.ai — True wall vectorization: typed centerline segments.

Closes memory/TOGAL_PARITY_REAUDIT.md #10: "True wall vectorization —
line-segment detection instead of the perimeter guess." (line 77 of that
audit: current wall LF is `4·sqrt(area)·1.8`, a formula with no relationship
to the actual floor plan layout, computed in spatial_reasoning.py.)

No trained wall-segmentation model exists in this codebase yet —
ai/inference_api.py's YOLO "wall" class only fires once best.pt exists and
was trained on it; mock mode returns walls=[] always (see
TakeoffAIInference._mock_analysis). Rather than block a real fix on that,
this derives actual wall centerlines from room bounding boxes, which *are*
reliably detected (and mocked) today:

  - Two rooms whose bbox edges are collinear and overlap along that line
    share a wall — the overlapping span becomes an INTERIOR wall segment.
  - Any portion of a room's bbox edge with no other room sharing it is on
    the building envelope — an EXTERIOR wall segment.

This is a real geometric derivation from detected room shapes (a standard
technique in floor-plan-to-BIM pipelines when explicit wall detection is
unavailable/unreliable), not a heuristic formula — it reflects the actual
layout the AI detected, and gets more accurate as room detection does.

If the AI *does* supply real "wall" class detections (once a trained model
exists), vectorize_walls() uses those instead: each wall bbox's long axis
becomes a centerline segment, classified exterior/interior by thickness
per AI_ARCHITECTURE_DESIGN.md's "Exterior walls (thick lines) / Interior
walls (thin lines)" guidance. EXTERIOR_THICKNESS_PX below is an
unclaibrated placeholder — there's no trained wall class in this sandbox to
calibrate it against; the room-adjacency path above is what's actually
exercised today, and matters more before that model exists.
"""

from typing import Optional

EXTERIOR_THICKNESS_PX = 10.0


def _room_edges(room: dict):
    x1, y1, x2, y2 = room["bbox"]
    rid = room["id"]
    return [
        ("h", y1, x1, x2, rid),  # top
        ("h", y2, x1, x2, rid),  # bottom
        ("v", x1, y1, y2, rid),  # left
        ("v", x2, y1, y2, rid),  # right
    ]


def _snap(value: float, tol: float) -> float:
    return round(value / tol) * tol if tol else value


def _sweep_group(edges):
    """
    edges: list of (start, end, room_id) all lying on the same line.
    Returns merged (start, end, wall_type, room_ids) runs via a 1D sweep:
    any sub-span covered by >=2 distinct rooms is interior, by exactly 1 is
    exterior, by 0 (a gap between rooms — no detected edge there) is dropped.
    """
    breakpoints = sorted({v for s, e, _ in edges for v in (s, e)})
    raw = []
    for p0, p1 in zip(breakpoints, breakpoints[1:]):
        if p1 - p0 < 1e-6:
            continue
        mid = (p0 + p1) / 2
        covering = sorted({rid for s, e, rid in edges if s <= mid <= e})
        if not covering:
            continue
        wall_type = "interior" if len(covering) >= 2 else "exterior"
        raw.append([p0, p1, wall_type, covering])

    merged = []
    for seg in raw:
        if merged and merged[-1][2] == seg[2] and merged[-1][3] == seg[3] and abs(merged[-1][1] - seg[0]) < 1e-6:
            merged[-1][1] = seg[1]
        else:
            merged.append(seg)
    return merged


def vectorize_walls_from_rooms(rooms: list, tol: float = 6.0) -> list:
    # Group edges by snapped coordinate (so near-collinear edges from
    # imprecise detections still merge), but keep the group's *actual*
    # coordinates to report — snapping is only a bucketing key, never
    # written into the output geometry, so exact-aligned input stays exact.
    groups = {}
    for room in rooms:
        if not room.get("bbox"):
            continue
        for orientation, fixed, s, e, rid in _room_edges(room):
            if s > e:
                s, e = e, s
            key = (orientation, _snap(fixed, tol))
            group = groups.setdefault(key, {"edges": [], "fixed_values": []})
            group["edges"].append((s, e, rid))
            group["fixed_values"].append(fixed)

    segments = []
    for (orientation, _snapped), group in groups.items():
        fixed = sum(group["fixed_values"]) / len(group["fixed_values"])
        for p0, p1, wall_type, room_ids in _sweep_group(group["edges"]):
            geometry = [[p0, fixed], [p1, fixed]] if orientation == "h" else [[fixed, p0], [fixed, p1]]
            segments.append({
                "id": f"wallseg_{orientation}{fixed}_{p0}_{len(segments)}",
                "wall_type": wall_type,
                "geometry": geometry,
                "length_px": round(p1 - p0, 2),
                "room_ids": room_ids,
                "source": "room_adjacency",
            })
    return segments


def vectorize_wall_detections(wall_boxes: list) -> list:
    segments = []
    for i, w in enumerate(wall_boxes):
        x1, y1, x2, y2 = w["bbox"]
        width, height = x2 - x1, y2 - y1
        thickness = min(width, height)
        length = max(width, height)
        if width >= height:
            y_c = (y1 + y2) / 2
            geometry = [[x1, y_c], [x2, y_c]]
        else:
            x_c = (x1 + x2) / 2
            geometry = [[x_c, y1], [x_c, y2]]
        wall_type = "exterior" if thickness >= EXTERIOR_THICKNESS_PX else "interior"
        segments.append({
            "id": w.get("id", f"walldet_{i}"),
            "wall_type": wall_type,
            "geometry": geometry,
            "length_px": round(length, 2),
            "thickness_px": round(thickness, 2),
            "confidence": w.get("confidence"),
            "room_ids": [],
            "source": "wall_detection",
        })
    return segments


def vectorize_walls(rooms: list, wall_detections: Optional[list] = None, tol: float = 6.0) -> list:
    """
    Real wall detections (once a trained model produces them) take priority
    over the room-adjacency derivation — they're actual detected geometry,
    not an inference from room shapes, and mixing both risks double-counting
    the same physical wall.
    """
    if wall_detections:
        return vectorize_wall_detections(wall_detections)
    return vectorize_walls_from_rooms(rooms, tol=tol)
