"""
Trade assemblies library + expansion engine.

Togal organizes a takeoff by "conditions/assemblies": one *measured* quantity
(a wall's linear feet, a room's floor area, a door count) expands into the many
material/labor line items a trade actually needs. A single ``Condition`` in this
codebase is one priced line (qty × unit_cost); an **Assembly** is the bundle — 1
LF of partition wall → metal studs + track + gypsum board (both faces) + tape &
finish + insulation, each with its own unit, per-driver factor, and waste.

This module is the generic (non-India) estimating layer that complements
``estimating/boq.py`` (India DSR/SOR). It's pure and unit-tested; unit costs are
injected via a cost book so the factors stay separate from prices.

    expand_assembly(ASSEMBLY_LIBRARY["interior_partition"], measured_qty=100, cost_book=...)
      -> [{item, trade, unit, quantity, unit_cost, amount}, ...]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional


@dataclass(frozen=True)
class AssemblyComponent:
    """One line item an assembly produces, per unit of the assembly's driver."""
    item: str
    unit: str            # output unit: sf | lf | ea | cy | gal | bf | lot
    factor: float        # output quantity per 1 driver unit (before waste)
    waste_pct: float = 0.0
    trade: str = ""      # optional per-component trade (else the assembly's trade)


@dataclass(frozen=True)
class Assembly:
    """A named measured item that expands into component line items."""
    key: str
    name: str
    trade: str
    driver_unit: str     # unit of the measured quantity that drives it: sf | lf | ea
    components: tuple = field(default_factory=tuple)


def _round(x: float) -> float:
    return round(x + 1e-9, 2)


def expand_assembly(assembly: Assembly, measured_qty: float,
                    cost_book: Optional[dict] = None) -> list[dict]:
    """Expand a measured quantity through an assembly into priced line items.

    ``measured_qty`` is in the assembly's ``driver_unit``. Each component's
    quantity = ``measured_qty × factor × (1 + waste_pct/100)``. ``cost_book`` maps
    ``item`` (or ``"assembly_key:item"``) → unit cost; missing costs price at 0.
    """
    if measured_qty < 0:
        raise ValueError("measured_qty must be non-negative")
    book = cost_book or {}
    lines: list[dict] = []
    for c in assembly.components:
        qty = _round(measured_qty * c.factor * (1 + c.waste_pct / 100.0))
        unit_cost = book.get(f"{assembly.key}:{c.item}", book.get(c.item, 0.0))
        lines.append({
            "assembly": assembly.key,
            "trade": c.trade or assembly.trade,
            "item": c.item,
            "unit": c.unit,
            "quantity": qty,
            "unit_cost": _round(unit_cost),
            "amount": _round(qty * unit_cost),
        })
    return lines


def expand_takeoff(measured: Iterable[dict], library: Optional[dict] = None,
                   cost_book: Optional[dict] = None) -> dict:
    """Expand a list of measured items into a priced, trade-rolled estimate.

    Each measured item: ``{"assembly": key, "quantity": q}``. Returns
    ``{line_items, by_trade, total}``. Unknown assembly keys are skipped and
    reported in ``skipped``.
    """
    lib = library if library is not None else ASSEMBLY_LIBRARY
    lines: list[dict] = []
    skipped: list[str] = []
    for m in measured:
        asm = lib.get(m.get("assembly"))
        if asm is None:
            skipped.append(m.get("assembly"))
            continue
        lines.extend(expand_assembly(asm, float(m.get("quantity", 0)), cost_book))

    by_trade: dict = {}
    for ln in lines:
        by_trade[ln["trade"]] = _round(by_trade.get(ln["trade"], 0.0) + ln["amount"])
    total = _round(sum(ln["amount"] for ln in lines))
    return {"line_items": lines, "by_trade": by_trade, "total": total, "skipped": skipped}


# --------------------------------------------------------------------------- #
# Seed library — realistic starter assemblies. Factors are editable defaults
# (US customary units); tune per project/region. Costs live in a cost book.
# --------------------------------------------------------------------------- #
def _a(key, name, trade, driver_unit, components):
    return Assembly(key=key, name=name, trade=trade, driver_unit=driver_unit,
                    components=tuple(components))

ASSEMBLY_LIBRARY: dict = {
    # 1 LF of interior partition, 9 ft tall, 5/8" GWB both faces on metal studs @16" o.c.
    "interior_partition": _a(
        "interior_partition", "Interior partition wall (per LF, 9ft)", "Drywall", "lf",
        [
            AssemblyComponent("Metal studs 25ga", "lf", 6.75, 5.0, "Framing"),   # ~0.75 studs/ft × 9 ft
            AssemblyComponent("Track (top & bottom)", "lf", 2.0, 5.0, "Framing"),
            AssemblyComponent("Gypsum board 5/8\"", "sf", 18.0, 10.0),           # 2 faces × 9 ft
            AssemblyComponent("Tape & joint finish", "sf", 18.0, 5.0),
            AssemblyComponent("Batt insulation", "sf", 9.0, 5.0, "Insulation"),
        ],
    ),
    # 1 SF of wall/ceiling face: 1 primer + 2 finish coats, ~350 sf/gal per coat.
    "paint_finish": _a(
        "paint_finish", "Paint finish (per SF, primer + 2 coats)", "Painting", "sf",
        [
            AssemblyComponent("Primer", "gal", 1 / 350.0, 5.0),
            AssemblyComponent("Finish paint", "gal", 2 / 350.0, 5.0),
        ],
    ),
    # 1 SF of floor: material + underlayment + adhesive.
    "resilient_flooring": _a(
        "resilient_flooring", "Resilient flooring (per SF)", "Flooring", "sf",
        [
            AssemblyComponent("Flooring material", "sf", 1.0, 10.0),
            AssemblyComponent("Underlayment", "sf", 1.0, 5.0),
            AssemblyComponent("Adhesive", "gal", 1 / 200.0, 5.0),
        ],
    ),
    # 1 interior door (3'0"×7'0"): slab + frame + hardware set + casing both sides.
    "interior_door": _a(
        "interior_door", "Interior door assembly (per EA)", "Doors", "ea",
        [
            AssemblyComponent("Door slab", "ea", 1.0, 0.0),
            AssemblyComponent("Frame", "ea", 1.0, 0.0),
            AssemblyComponent("Hardware set", "ea", 1.0, 0.0),
            AssemblyComponent("Casing", "lf", 34.0, 10.0, "Finish Carpentry"),
        ],
    ),
    # 1 SF of suspended acoustic ceiling: tile + grid + hanger wire.
    "acoustic_ceiling": _a(
        "acoustic_ceiling", "Suspended acoustic ceiling (per SF)", "Ceilings", "sf",
        [
            AssemblyComponent("Ceiling tile", "sf", 1.0, 10.0),
            AssemblyComponent("Grid (main + cross tee)", "lf", 0.9, 5.0),
            AssemblyComponent("Hanger wire", "ea", 0.25, 0.0),
        ],
    ),
    # 1 SF of 4" slab-on-grade: concrete volume + vapor barrier + rebar.
    "slab_on_grade_4in": _a(
        "slab_on_grade_4in", "4\" slab on grade (per SF)", "Concrete", "sf",
        [
            AssemblyComponent("Concrete 4\"", "cy", (4 / 12) / 27.0, 5.0),       # SF×thickness/27
            AssemblyComponent("Vapor barrier", "sf", 1.0, 10.0),
            AssemblyComponent("Rebar / WWF", "sf", 1.0, 5.0, "Rebar"),
        ],
    ),
}
