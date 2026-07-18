"""
Takeoff → assemblies auto-mapping.

Turns a drawing's measured takeoff quantities (the ``[{trade, item, quantity,
unit}]`` rows the AI/vector pipeline writes to ``TakeoffResult.quantities_data``)
into assembly drivers, then expands them through ``estimating/assemblies.py`` into
a priced, trade-rolled estimate. This is what makes the assemblies library live:
open a drawing → get an estimate, no hand entry.

Conservative by design — only unambiguous drivers are auto-mapped (floor area,
wall linear feet, door count); everything else is opt-in via extra rules, so the
estimate never invents quantities. Pure and unit-tested.
"""

from __future__ import annotations

from typing import Iterable, Optional

from .assemblies import expand_takeoff

# driver key -> assembly key. Only high-confidence, one-to-one mappings by default.
DEFAULT_TAKEOFF_RULES: list[tuple] = [
    ("floor_area_sf", "resilient_flooring"),
    ("wall_lf", "interior_partition"),
    ("door_count", "interior_door"),
]


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def drivers_from_quantities(quantities: Iterable[dict]) -> dict:
    """Extract assembly drivers from takeoff quantity rows.

    Recognizes (case-insensitive, unit-aware):
      - **floor_area_sf** — sum of Flooring rows in ``sf``
      - **wall_lf** — a "wall linear" row in ``lf``
      - **door_count** — a Doors/interior-door row in ``ea``
    Unknown rows are ignored. Returns only the drivers actually found.
    """
    floor_sf = 0.0
    wall_lf = 0.0
    door_count = 0.0
    for row in quantities or []:
        trade = str(row.get("trade", "")).lower()
        item = str(row.get("item", "")).lower()
        unit = str(row.get("unit", "")).lower()
        qty = _num(row.get("quantity"))

        if unit == "sf" and (trade == "flooring" or "floor" in item):
            floor_sf += qty
        elif unit == "lf" and "wall" in item and "linear" in item:
            wall_lf += qty
        elif unit == "ea" and (trade == "doors" or ("door" in item and "interior" in item)):
            door_count += qty

    drivers: dict = {}
    if floor_sf > 0:
        drivers["floor_area_sf"] = round(floor_sf, 2)
    if wall_lf > 0:
        drivers["wall_lf"] = round(wall_lf, 2)
    if door_count > 0:
        drivers["door_count"] = door_count
    return drivers


def takeoff_to_assemblies(drivers: dict, rules: Optional[list] = None) -> list[dict]:
    """Map a drivers dict to ``[{assembly, quantity}]`` via the mapping rules."""
    rules = rules if rules is not None else DEFAULT_TAKEOFF_RULES
    measured = []
    for driver_key, assembly_key in rules:
        qty = drivers.get(driver_key)
        if qty:
            measured.append({"assembly": assembly_key, "quantity": float(qty)})
    return measured


def estimate_from_takeoff(quantities: Iterable[dict], *, cost_book: Optional[dict] = None,
                          rules: Optional[list] = None, library: Optional[dict] = None) -> dict:
    """Full path: takeoff quantity rows → drivers → assemblies → priced estimate.

    Returns the ``expand_takeoff`` result plus the ``drivers`` and ``measured``
    that produced it (for transparency / a UI to show what drove each item).
    """
    drivers = drivers_from_quantities(quantities)
    measured = takeoff_to_assemblies(drivers, rules)
    estimate = expand_takeoff(measured, library=library, cost_book=cost_book)
    return {"drivers": drivers, "measured": measured, **estimate}
