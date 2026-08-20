"""Tests for the trade assemblies library + expansion engine."""

import pytest

from estimating.assemblies import (
    ASSEMBLY_LIBRARY,
    Assembly,
    AssemblyComponent,
    expand_assembly,
    expand_takeoff,
)


def _simple_assembly():
    return Assembly(
        key="wall", name="Test wall", trade="Drywall", driver_unit="lf",
        components=(
            AssemblyComponent("Gypsum board", "sf", 18.0, 10.0),   # 2 faces × 9 ft, +10% waste
            AssemblyComponent("Studs", "lf", 6.75, 0.0, "Framing"),
        ),
    )


def test_expand_applies_factor_and_waste():
    lines = expand_assembly(_simple_assembly(), 100.0)
    board = next(l for l in lines if l["item"] == "Gypsum board")
    assert board["quantity"] == pytest.approx(100 * 18 * 1.10)   # 1980
    assert board["unit"] == "sf"


def test_component_trade_override():
    lines = expand_assembly(_simple_assembly(), 10.0)
    studs = next(l for l in lines if l["item"] == "Studs")
    assert studs["trade"] == "Framing"          # overrides assembly trade
    board = next(l for l in lines if l["item"] == "Gypsum board")
    assert board["trade"] == "Drywall"          # inherits assembly trade


def test_pricing_from_cost_book():
    cost_book = {"Gypsum board": 0.55, "wall:Studs": 1.20}   # item + assembly-scoped keys
    lines = expand_assembly(_simple_assembly(), 100.0, cost_book)
    board = next(l for l in lines if l["item"] == "Gypsum board")
    studs = next(l for l in lines if l["item"] == "Studs")
    assert board["unit_cost"] == 0.55
    assert board["amount"] == pytest.approx(round(100 * 18 * 1.10 * 0.55, 2))
    assert studs["unit_cost"] == 1.20           # matched the assembly-scoped key


def test_missing_cost_prices_zero():
    lines = expand_assembly(_simple_assembly(), 5.0)
    assert all(l["unit_cost"] == 0.0 and l["amount"] == 0.0 for l in lines)


def test_negative_quantity_rejected():
    with pytest.raises(ValueError):
        expand_assembly(_simple_assembly(), -1.0)


def test_expand_takeoff_rolls_up_by_trade_and_total():
    measured = [
        {"assembly": "wall", "quantity": 100.0},
        {"assembly": "unknown_key", "quantity": 5.0},   # skipped
    ]
    cost_book = {"Gypsum board": 1.0, "Studs": 2.0}
    lib = {"wall": _simple_assembly()}
    out = expand_takeoff(measured, lib, cost_book)

    assert out["skipped"] == ["unknown_key"]
    assert set(out["by_trade"]) == {"Drywall", "Framing"}
    # total = sum of every component amount
    assert out["total"] == pytest.approx(sum(l["amount"] for l in out["line_items"]))
    assert out["by_trade"]["Drywall"] == pytest.approx(round(100 * 18 * 1.10 * 1.0, 2))


# --- seed library sanity ---------------------------------------------------
def test_library_assemblies_are_well_formed():
    assert "interior_partition" in ASSEMBLY_LIBRARY
    for key, asm in ASSEMBLY_LIBRARY.items():
        assert asm.key == key
        assert asm.driver_unit in ("sf", "lf", "ea")
        assert asm.components, f"{key} has no components"
        for c in asm.components:
            assert c.factor > 0 and c.unit and c.item


def test_interior_partition_expands_both_faces():
    lines = expand_assembly(ASSEMBLY_LIBRARY["interior_partition"], 50.0)
    board = next(l for l in lines if l["item"].startswith("Gypsum"))
    # 2 faces × 9 ft × 50 LF × 1.10 waste
    assert board["quantity"] == pytest.approx(50 * 18 * 1.10)
