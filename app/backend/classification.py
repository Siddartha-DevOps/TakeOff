"""
Classification-library logic (Togal's "classification library template").

A classification item is a named measurable condition: trade, annotation type
(count / line / area), unit, color, waste %. A template bundles many; applying a
template to a project creates ``Condition`` rows. Pure (no DB) and unit-tested;
DB I/O is in routes/classification_routes.py.
"""

from __future__ import annotations

from typing import Optional

VALID_ANNOTATION_TYPES = ("count", "line", "area")
# annotation type -> its natural quantity unit
_DEFAULT_UNIT = {"count": "ea", "line": "lf", "area": "sf"}

# A compact, realistic starter library across the common trades.
DEFAULT_CLASSIFICATIONS: list[dict] = [
    {"name": "Interior partition wall", "trade": "Drywall", "annotation_type": "line", "unit": "lf", "color": "#e6194B"},
    {"name": "Room floor area", "trade": "Flooring", "annotation_type": "area", "unit": "sf", "color": "#3cb44b"},
    {"name": "Wall paint", "trade": "Painting", "annotation_type": "area", "unit": "sf", "color": "#4363d8"},
    {"name": "Ceiling", "trade": "Ceilings", "annotation_type": "area", "unit": "sf", "color": "#f58231"},
    {"name": "Interior door", "trade": "Doors", "annotation_type": "count", "unit": "ea", "color": "#911eb4"},
    {"name": "Window", "trade": "Windows", "annotation_type": "count", "unit": "ea", "color": "#42d4f4"},
    {"name": "Electrical outlet", "trade": "Electrical", "annotation_type": "count", "unit": "ea", "color": "#f032e6"},
    {"name": "Plumbing fixture", "trade": "Plumbing", "annotation_type": "count", "unit": "ea", "color": "#469990"},
    {"name": "Slab on grade", "trade": "Concrete", "annotation_type": "area", "unit": "sf", "color": "#808000"},
]


def validate_item(item: dict) -> Optional[dict]:
    """Normalize/validate a classification item, or None if invalid.

    Requires a name and trade; annotation_type must be count/line/area (defaults
    to 'count'); unit defaults from the annotation type; color/waste optional.
    """
    name = (item.get("name") or "").strip()
    trade = (item.get("trade") or "").strip()
    if not name or not trade:
        return None
    atype = (item.get("annotation_type") or "count").strip().lower()
    if atype not in VALID_ANNOTATION_TYPES:
        return None
    unit = (item.get("unit") or _DEFAULT_UNIT[atype]).strip().lower()
    try:
        waste = float(item.get("waste_percent", 0) or 0)
    except (TypeError, ValueError):
        waste = 0.0
    return {
        "name": name, "trade": trade, "annotation_type": atype, "unit": unit,
        "color": item.get("color") or "#6366f1", "waste_percent": waste,
    }


def validate_items(items) -> list[dict]:
    """Validate a list of items, dropping invalid ones."""
    out = []
    for it in items or []:
        v = validate_item(it)
        if v:
            out.append(v)
    return out


def default_template() -> dict:
    """The built-in starter classification template."""
    return {
        "name": "Standard classifications",
        "description": "Common trade conditions to start from — edit to fit your estimating standards.",
        "items": [validate_item(i) for i in DEFAULT_CLASSIFICATIONS],
    }


def items_to_conditions(items, project_id: int) -> list[dict]:
    """Turn validated classification items into Condition row kwargs for a project."""
    conditions = []
    for it in validate_items(items):
        conditions.append({
            "project_id": project_id,
            "name": it["name"],
            "trade": it["trade"],
            "annotation_type": it["annotation_type"],
            "unit": it["unit"],
            "color": it["color"],
            "waste_percent": it["waste_percent"],
        })
    return conditions
