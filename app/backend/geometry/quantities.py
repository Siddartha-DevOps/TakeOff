"""
Map exact vector geometry to Togal-style takeoff output: Area / Line / Count.

Togal's one-click AUTODETECT produces three measurement primitives on the real
plan — **Area** (sqft), **Line** (linear ft) and **Count** (each) — which the
estimator then classifies into conditions. This module turns the geometry
engine's output into exactly those primitives plus a flat trade-quantity list
the existing UI / Excel export already understands.

Everything here is derived from exact vector geometry, so the numbers are not
predictions — there is no model and no confidence to hedge.
"""

from __future__ import annotations

from typing import Any

# Assumed wall height for surface-area derivations until ceilings are measured.
WALL_HEIGHT_FT = 9.0


def vector_quantities(
    measure_result: dict[str, Any], symbol_counts: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Flat trade-quantity rows (the shape the QuantitiesPanel / export expect).

    `symbol_counts` is `match_symbols()`'s per-type count dict (door/window/
    fixture/...) — optional so existing measure-only callers are unaffected.
    """
    summary = measure_result.get("summary", {})
    total_area = round(float(summary.get("totalArea", 0.0)), 1)
    walls_lf = round(float(summary.get("walls_lf", 0.0)), 1)
    n_rooms = int(summary.get("rooms", 0))

    rows: list[dict[str, Any]] = []

    # Area primitives.
    if total_area > 0:
        rows.append({"trade": "Areas", "item": "Floor area (net)", "quantity": total_area, "unit": "sf"})
        rows.append({"trade": "Areas", "item": "Ceiling area", "quantity": total_area, "unit": "sf"})

    # Line primitives.
    if walls_lf > 0:
        gypsum_sf = round(walls_lf * WALL_HEIGHT_FT * 2)  # both faces
        rows.append({"trade": "Walls", "item": "Wall linear feet", "quantity": walls_lf, "unit": "lf"})
        rows.append({
            "trade": "Walls",
            "item": f"Gypsum board (both faces, {WALL_HEIGHT_FT:g}ft walls)",
            "quantity": gypsum_sf,
            "unit": "sf",
        })

    # Count primitives: spaces, plus one row per detected symbol type
    # (door/window/fixture/...) so AUTODETECT's third primitive — Count —
    # actually reaches the Quantities panel instead of only the API response.
    if n_rooms > 0:
        rows.append({"trade": "Counts", "item": "Spaces", "quantity": n_rooms, "unit": "ea"})

    for symbol_type, qty in sorted((symbol_counts or {}).items()):
        if qty > 0:
            rows.append({"trade": "Counts", "item": f"{symbol_type.title()}s", "quantity": int(qty), "unit": "ea"})

    return rows


def autodetect_from_measure(
    measure_result: dict[str, Any], symbol_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Assemble the one-click AUTODETECT response from a measurement result.

    Returns Togal's three primitives explicitly (``area``/``line``/``count``),
    the per-space geometry for canvas overlay, trade quantities, and the page
    dimensions the frontend needs to position the overlay.
    """
    summary = measure_result.get("summary", {})
    rooms = measure_result.get("rooms", [])

    # `area` = per-space polygons (the things you classify into flooring, etc.).
    area = [
        {
            "id": r.get("id"),
            "label": r.get("label", "Space"),
            "sqft": r.get("area"),
            "perimeter_ft": r.get("perimeter_ft"),
            "bbox": r.get("bbox"),
            "centroid": r.get("centroid"),
            "confidence": r.get("confidence", 1.0),
            "geojson": r.get("geojson"),  # populated by the route after serialization
        }
        for r in rooms
    ]

    return {
        "method": measure_result.get("method", "vector"),
        "is_vector": measure_result.get("is_vector", True),
        "scale_ratio": measure_result.get("scale_ratio"),
        "page": measure_result.get("page"),
        # Togal's three AI primitives, summarized.
        "primitives": {
            "area": round(float(summary.get("totalArea", 0.0)), 1),   # sqft
            "line": round(float(summary.get("walls_lf", 0.0)), 1),    # linear ft
            "count": int(summary.get("rooms", 0)),                    # each
        },
        "area": area,
        "summary": summary,
        "quantities": vector_quantities(measure_result, symbol_counts),
        "accuracy_note": measure_result.get("accuracy_note"),
    }
