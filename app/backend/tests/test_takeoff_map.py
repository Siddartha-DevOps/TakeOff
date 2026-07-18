"""Tests for takeoff-quantities → assemblies auto-mapping."""

import pytest

from estimating.takeoff_map import (
    DEFAULT_TAKEOFF_RULES,
    drivers_from_quantities,
    estimate_from_takeoff,
    takeoff_to_assemblies,
)

# The shape inference_api / geometry write to TakeoffResult.quantities_data.
SAMPLE_QUANTITIES = [
    {"trade": "Flooring", "item": "Hardwood flooring", "quantity": 420, "unit": "sf"},
    {"trade": "Flooring", "item": "Carpet flooring", "quantity": 510, "unit": "sf"},
    {"trade": "Drywall", "item": "Wall linear footage", "quantity": 312, "unit": "lf"},
    {"trade": "Doors", "item": "Interior doors", "quantity": 8, "unit": "ea"},
    {"trade": "Windows", "item": "Window openings", "quantity": 10, "unit": "ea"},
    {"trade": "Electrical", "item": "Outlets (est.)", "quantity": 40, "unit": "ea"},
]


def test_drivers_extracted_from_quantities():
    d = drivers_from_quantities(SAMPLE_QUANTITIES)
    assert d["floor_area_sf"] == 930          # 420 + 510 summed
    assert d["wall_lf"] == 312
    assert d["door_count"] == 8
    assert "window" not in d                   # windows not auto-mapped (conservative)


def test_drivers_ignores_unknown_and_missing():
    assert drivers_from_quantities([]) == {}
    assert drivers_from_quantities([{"trade": "Electrical", "item": "Outlets", "quantity": 5, "unit": "ea"}]) == {}


def test_takeoff_to_assemblies_uses_rules():
    measured = takeoff_to_assemblies({"floor_area_sf": 930, "wall_lf": 312, "door_count": 8})
    keys = {m["assembly"]: m["quantity"] for m in measured}
    assert keys == {"resilient_flooring": 930, "interior_partition": 312, "interior_door": 8}


def test_takeoff_to_assemblies_skips_zero_drivers():
    measured = takeoff_to_assemblies({"floor_area_sf": 0, "wall_lf": 100})
    assert measured == [{"assembly": "interior_partition", "quantity": 100.0}]


def test_custom_rules_override():
    rules = [("floor_area_sf", "acoustic_ceiling")]
    measured = takeoff_to_assemblies({"floor_area_sf": 500}, rules=rules)
    assert measured == [{"assembly": "acoustic_ceiling", "quantity": 500.0}]


def test_estimate_from_takeoff_end_to_end():
    cost_book = {"Flooring material": 3.50, "Gypsum board 5/8\"": 0.55, "Door slab": 180}
    out = estimate_from_takeoff(SAMPLE_QUANTITIES, cost_book=cost_book)

    assert out["drivers"]["floor_area_sf"] == 930
    assert {m["assembly"] for m in out["measured"]} == {
        "resilient_flooring", "interior_partition", "interior_door"}
    # priced line items exist and roll up
    assert out["total"] > 0
    assert "Flooring" in out["by_trade"] and "Drywall" in out["by_trade"]
    assert out["total"] == pytest.approx(sum(l["amount"] for l in out["line_items"]))


def test_default_rules_are_conservative():
    # Only the three high-confidence drivers are auto-mapped.
    assert {a for _, a in DEFAULT_TAKEOFF_RULES} == {
        "resilient_flooring", "interior_partition", "interior_door"}
