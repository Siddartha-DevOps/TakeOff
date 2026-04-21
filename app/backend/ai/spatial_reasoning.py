"""
TakeOff.ai Spatial Reasoning Layer.
Runs after YOLOv8 inference to add:
  - Room adjacency graph
  - Window/door-to-room assignment
  - Natural light scores
  - Circulation score
  - Scale detection (OCR → room heuristics → fallback)
  - Real construction quantities with trade breakdowns
"""
import json
import numpy as np
from typing import List, Dict, Optional, Tuple, Any


class ScaleDetector:
    """Detect drawing scale and convert pixels to real feet."""
    TYPICAL_FT = {"bedroom": 11.0, "bathroom": 6.0, "kitchen": 10.0, "living": 14.0}

    def get_scale(self, image_path=None, rooms=None, walls=None):
        """Returns (px_per_ft, confidence, method)."""
        if image_path:
            result = self._from_ocr(image_path)
            if result: return result

        if rooms:
            result = self._from_rooms(rooms)
            if result: return result

        return (9.0, 0.3, "fallback_standard")

    def _from_ocr(self, image_path):
        try:
            import re, cv2
            from paddleocr import PaddleOCR
            ocr = PaddleOCR(use_angle_cls=False, lang='en', show_log=False)
            img = cv2.imread(image_path)
            if img is None: return None
            result = ocr.ocr(img, cls=False)
            text = " ".join(line[1][0] for block in (result or []) for line in (block or []) if line)
            m = re.search(r'1/(\d+)"\s*=\s*1\'-0"', text, re.I)
            if m:
                px_per_ft = 300 * 12 / float(m.group(1))
                return (px_per_ft, 0.95, f"ocr:{m.group(0)}")
        except Exception:
            pass
        return None

    def _from_rooms(self, rooms):
        scales = []
        for r in rooms:
            if r.get("label") not in self.TYPICAL_FT: continue
            b = r.get("bbox", [])
            if len(b) < 4: continue
            shorter = min(b[2]-b[0], b[3]-b[1])
            if shorter > 10:
                scales.append(shorter / self.TYPICAL_FT[r["label"]])
        if scales:
            return (float(np.median(scales)), 0.75, "room_reference")
        return None


def bbox_iou(b1, b2):
    xi1, yi1 = max(b1[0],b2[0]), max(b1[1],b2[1])
    xi2, yi2 = min(b1[2],b2[2]), min(b1[3],b2[3])
    inter = max(0, xi2-xi1) * max(0, yi2-yi1)
    a1 = (b1[2]-b1[0])*(b1[3]-b1[1])
    a2 = (b2[2]-b2[0])*(b2[3]-b2[1])
    return inter / (a1 + a2 - inter + 1e-9)


def assign_openings(rooms, openings, tol=16):
    """Assign each door/window to the nearest room."""
    mapping = {r["id"]: [] for r in rooms}
    for op in openings:
        ob = op["bbox"]
        ob_exp = [ob[0]-tol, ob[1]-tol, ob[2]+tol, ob[3]+tol]
        best_room, best_overlap = None, 0
        for room in rooms:
            iou = bbox_iou(ob_exp, room["bbox"])
            if iou > best_overlap:
                best_overlap, best_room = iou, room["id"]
        if best_room and best_overlap > 0:
            mapping[best_room].append(op["id"])
    return mapping


def circulation_score(rooms, adj_matrix):
    """BFS from living room — fraction reachable."""
    if not rooms: return 0.0
    living = next((i for i, r in enumerate(rooms) if r["label"] == "living"), 0)
    visited, queue = set(), [living]
    while queue:
        cur = queue.pop(0)
        if cur in visited: continue
        visited.add(cur)
        queue.extend(j for j, conn in enumerate(adj_matrix[cur]) if conn and j not in visited)
    return round(len(visited) / len(rooms), 2)


def build_adjacency(rooms, tol=10):
    n = len(rooms)
    adj = [[0]*n for _ in range(n)]
    for i, ra in enumerate(rooms):
        for j, rb in enumerate(rooms):
            if i >= j: continue
            ba = ra["bbox"]; bb = rb["bbox"]
            exp_a = [ba[0]-tol, ba[1]-tol, ba[2]+tol, ba[3]+tol]
            if bbox_iou(exp_a, bb) > 0:
                adj[i][j] = adj[j][i] = 1
    return adj


def derive_quantities(rooms, walls, doors, windows, scale):
    """Build full trade-level quantity list."""
    qs = []
    flooring = {"bedroom": "Carpet", "bathroom": "Tile", "kitchen": "Tile"}
    by_mat = {}
    for r in rooms:
        mat = flooring.get(r["label"], "Hardwood")
        area_sf = round(r["area"] / (scale**2), 1)
        by_mat[mat] = by_mat.get(mat, 0) + area_sf

    for mat, area in by_mat.items():
        qs.append({"trade":"Flooring","item":f"{mat} flooring","quantity":area,"unit":"sf"})

    total_lf = sum(max(w["bbox"][2]-w["bbox"][0], w["bbox"][3]-w["bbox"][1]) / scale for w in walls)
    total_lf = round(total_lf, 1)
    drywall_sf = round(total_lf * 9, 1)
    ceiling_sf = round(sum(r["area"] / (scale**2) for r in rooms), 1)
    paint_sf   = round(drywall_sf + ceiling_sf, 1)

    qs += [
        {"trade":"Drywall",    "item":"Wall linear footage",    "quantity":total_lf,                 "unit":"lf"},
        {"trade":"Drywall",    "item":"Gypsum board (9ft walls)","quantity":drywall_sf,              "unit":"sf"},
        {"trade":"Painting",   "item":"Paintable surface",      "quantity":paint_sf,                 "unit":"sf"},
        {"trade":"Doors",      "item":"Interior doors (3'-0\")", "quantity":len(doors),              "unit":"ea"},
        {"trade":"Windows",    "item":"Window openings",         "quantity":len(windows),            "unit":"ea"},
        {"trade":"Electrical", "item":"Outlets (est.)",          "quantity":max(1,int(ceiling_sf/50)),"unit":"ea"},
        {"trade":"Electrical", "item":"Light fixtures (est.)",   "quantity":len(rooms)+len([r for r in rooms if r["label"] in ("bathroom","kitchen")]),"unit":"ea"},
        {"trade":"Plumbing",   "item":"Fixtures (est.)",         "quantity":sum(3 if r["label"]=="bathroom" else 2 for r in rooms if r["label"] in ("bathroom","kitchen")),"unit":"ea"},
    ]
    return qs


def enrich_takeoff_result(detection_json_str: str, image_path: str = None) -> Dict[str, Any]:
    """
    Call this after YOLOv8 inference. Adds spatial intelligence.

    Usage in takeoff_routes.py:
        enriched = enrich_takeoff_result(json.dumps(raw_detection), drawing.file_path)
        db_result.detection_data  = json.dumps(enriched["detection"])
        db_result.quantities_data = json.dumps(enriched["quantities"])
    """
    detection = json.loads(detection_json_str) if isinstance(detection_json_str, str) else detection_json_str

    rooms   = detection.get("rooms",   [])
    walls   = detection.get("walls",   [])
    doors   = detection.get("doors",   [])
    windows = detection.get("windows", [])

    # Scale detection
    detector = ScaleDetector()
    scale, conf, method = detector.get_scale(image_path=image_path, rooms=rooms, walls=walls)

    # Assign openings to rooms
    door_map   = assign_openings(rooms, doors)
    window_map = assign_openings(rooms, windows)

    # Enrich room data
    enriched_rooms = []
    for r in rooms:
        enriched_rooms.append({
            **r,
            "area_sqft":      round(r["area"] / (scale**2), 1),
            "doors":          door_map.get(r["id"], []),
            "windows":        window_map.get(r["id"], []),
            "natural_light":  round(min(1.0, len(window_map.get(r["id"], [])) / 2.0), 2),
        })

    # Adjacency matrix
    adj = build_adjacency(rooms)

    # Spatial scores
    circ  = circulation_score(rooms, adj)
    nl    = round(float(np.mean([r["natural_light"] for r in enriched_rooms])) if enriched_rooms else 0, 2)
    total = round(sum(r["area"] / (scale**2) for r in rooms), 1)

    from collections import Counter
    room_count = dict(Counter(r["label"] for r in rooms))

    quantities = derive_quantities(rooms, walls, doors, windows, scale)

    return {
        "detection": {
            **detection,
            "rooms": enriched_rooms,
            "room_graph": {"adjacency_matrix": adj, "room_count": room_count},
            "spatial_metrics": {
                "total_area_sqft":     total,
                "circulation_score":   circ,
                "natural_light_score": nl,
                "scale_px_per_ft":     round(scale, 2),
                "scale_confidence":    round(conf, 2),
                "scale_method":        method,
            }
        },
        "quantities": quantities,
        "summary": {**detection.get("summary", {}), "totalArea": total, "roomTypes": room_count}
    }