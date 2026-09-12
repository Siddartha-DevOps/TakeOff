"""Tests for assembly/cost-book persistence helpers (pure — no DB)."""

from types import SimpleNamespace

from estimating.assemblies import ASSEMBLY_LIBRARY
from estimating.persistence import (
    assembly_to_dict,
    cost_book_to_dict,
    cost_book_to_map,
    seed_rows_from_library,
)


def test_seed_rows_cover_the_library():
    rows = seed_rows_from_library()
    assert len(rows) == len(ASSEMBLY_LIBRARY)
    keys = {r["key"] for r in rows}
    assert "interior_partition" in keys
    part = next(r for r in rows if r["key"] == "interior_partition")
    assert part["driver_unit"] == "lf"
    assert part["components"]                       # has line items
    # component trade defaults to the assembly trade when unset
    assert all(c["trade"] for c in part["components"])


def test_seed_rows_component_shape():
    row = seed_rows_from_library()[0]
    c = row["components"][0]
    assert set(c) == {"item", "unit", "factor", "waste_pct", "trade"}


def test_assembly_to_dict_duck_typed():
    comp = SimpleNamespace(id=1, item="Gypsum board", unit="sf", factor=18.0, waste_pct=10.0, trade="Drywall")
    asm = SimpleNamespace(id=7, key="wall", name="Wall", trade="Drywall", driver_unit="lf", components=[comp])
    d = assembly_to_dict(asm)
    assert d["id"] == 7 and d["key"] == "wall"
    assert d["components"][0]["item"] == "Gypsum board"


def test_cost_book_to_dict_and_map():
    items = [SimpleNamespace(id=1, item="Gypsum board", unit="sf", unit_cost=0.55),
             SimpleNamespace(id=2, item="Door slab", unit="ea", unit_cost=180.0)]
    cb = SimpleNamespace(id=3, name="US default", currency="USD", is_default=True, items=items)

    d = cost_book_to_dict(cb)
    assert d["is_default"] is True and len(d["items"]) == 2

    m = cost_book_to_map(cb)
    assert m == {"Gypsum board": 0.55, "Door slab": 180.0}


def test_cost_book_to_map_empty():
    assert cost_book_to_map(SimpleNamespace(items=None)) == {}
