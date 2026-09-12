"""
Persistence helpers for assemblies + cost books.

Bridges the pure assemblies engine (``estimating/assemblies.py``) and the DB
models (``models.Assembly`` / ``AssemblyComponent`` / ``CostBook`` / ``CostItem``):
seed an org from the code library, serialize rows for the API, and turn a stored
cost book into the ``{item: unit_cost}`` map the expansion engine consumes.

Pure (operates on the code library and duck-typed row objects) — unit-tested; the
DB reads/writes live in the route layer.
"""

from __future__ import annotations

from typing import Iterable, Optional

from .assemblies import ASSEMBLY_LIBRARY


def seed_rows_from_library(library: Optional[dict] = None) -> list[dict]:
    """Flatten the code assembly library into persistable rows.

    Each row: ``{key, name, trade, driver_unit, components: [{item, unit, factor,
    waste_pct, trade}]}`` — exactly what a route needs to create ``Assembly`` +
    ``AssemblyComponent`` rows for a new org.
    """
    lib = library if library is not None else ASSEMBLY_LIBRARY
    rows = []
    for asm in lib.values():
        rows.append({
            "key": asm.key,
            "name": asm.name,
            "trade": asm.trade,
            "driver_unit": asm.driver_unit,
            "components": [
                {"item": c.item, "unit": c.unit, "factor": c.factor,
                 "waste_pct": c.waste_pct, "trade": c.trade or asm.trade}
                for c in asm.components
            ],
        })
    return rows


def assembly_to_dict(assembly) -> dict:
    """Serialize an Assembly row (or duck-typed object) for the API."""
    return {
        "id": getattr(assembly, "id", None),
        "key": assembly.key,
        "name": assembly.name,
        "trade": assembly.trade,
        "driver_unit": assembly.driver_unit,
        "components": [
            {"id": getattr(c, "id", None), "item": c.item, "unit": c.unit,
             "factor": c.factor, "waste_pct": c.waste_pct, "trade": c.trade}
            for c in (assembly.components or [])
        ],
    }


def cost_book_to_dict(cost_book) -> dict:
    """Serialize a CostBook row (with its items) for the API."""
    return {
        "id": getattr(cost_book, "id", None),
        "name": cost_book.name,
        "currency": cost_book.currency,
        "is_default": bool(cost_book.is_default),
        "items": [
            {"id": getattr(i, "id", None), "item": i.item, "unit": i.unit,
             "unit_cost": i.unit_cost}
            for i in (cost_book.items or [])
        ],
    }


def cost_book_to_map(cost_book) -> dict:
    """Turn a stored CostBook into the ``{item: unit_cost}`` map expand_* consumes."""
    return {i.item: i.unit_cost for i in (getattr(cost_book, "items", None) or [])}


def estimate_to_dict(estimate, *, include_data: bool = True) -> dict:
    """Serialize an Estimate row for the API.

    ``data`` (the estimate snapshot JSON) is parsed and inlined when
    ``include_data`` (detail view); list views can omit it for compactness.
    """
    import json as _json

    out = {
        "id": getattr(estimate, "id", None),
        "name": estimate.name,
        "project_id": estimate.project_id,
        "drawing_id": estimate.drawing_id,
        "cost_book_id": estimate.cost_book_id,
        "total": estimate.total,
        "created_at": estimate.created_at.isoformat() if getattr(estimate, "created_at", None) else None,
    }
    if include_data:
        try:
            out["data"] = _json.loads(estimate.data) if estimate.data else {}
        except (ValueError, TypeError):
            out["data"] = {}
    return out
