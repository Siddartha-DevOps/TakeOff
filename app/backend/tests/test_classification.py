"""Tests for classification-library logic (pure)."""

from classification import (
    DEFAULT_CLASSIFICATIONS,
    default_template,
    items_to_conditions,
    validate_item,
    validate_items,
)


def test_validate_item_normalizes():
    v = validate_item({"name": " Door ", "trade": "Doors", "annotation_type": "COUNT"})
    assert v["name"] == "Door" and v["trade"] == "Doors"
    assert v["annotation_type"] == "count" and v["unit"] == "ea"   # unit defaulted
    assert v["color"] and v["waste_percent"] == 0.0


def test_validate_item_defaults_unit_by_type():
    assert validate_item({"name": "Wall", "trade": "Drywall", "annotation_type": "line"})["unit"] == "lf"
    assert validate_item({"name": "Floor", "trade": "Flooring", "annotation_type": "area"})["unit"] == "sf"


def test_validate_item_rejects_bad():
    assert validate_item({"name": "", "trade": "X"}) is None            # no name
    assert validate_item({"name": "X", "trade": ""}) is None            # no trade
    assert validate_item({"name": "X", "trade": "Y", "annotation_type": "blob"}) is None


def test_validate_items_drops_invalid():
    items = [{"name": "Door", "trade": "Doors"}, {"name": "", "trade": "Z"}]
    assert len(validate_items(items)) == 1


def test_default_template_is_valid():
    tpl = default_template()
    assert tpl["name"] and tpl["items"]
    assert len(tpl["items"]) == len(DEFAULT_CLASSIFICATIONS)
    assert all(i["annotation_type"] in ("count", "line", "area") for i in tpl["items"])


def test_items_to_conditions_shape():
    conds = items_to_conditions(default_template()["items"], project_id=42)
    assert conds and all(c["project_id"] == 42 for c in conds)
    c0 = conds[0]
    assert set(c0) == {"project_id", "name", "trade", "annotation_type", "unit", "color", "waste_percent"}
