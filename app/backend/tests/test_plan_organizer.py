"""Tests for plan-set discipline grouping + ordering."""

from plan_organizer import (
    discipline_from_sheet_number,
    discipline_name,
    group_by_discipline,
)


def test_discipline_from_sheet_number():
    assert discipline_from_sheet_number("A-101") == "A"
    assert discipline_from_sheet_number("S2.1") == "S"
    assert discipline_from_sheet_number("FP-1") == "FP"
    assert discipline_from_sheet_number("M101") == "M"
    assert discipline_from_sheet_number("101") is None
    assert discipline_from_sheet_number(None) is None


def test_discipline_name():
    assert discipline_name("A") == "Architectural"
    assert discipline_name("E") == "Electrical"
    assert discipline_name("ZZ") == "Other"


def test_group_orders_disciplines_conventionally():
    sheets = [
        {"id": 1, "sheet_number": "E-101"},
        {"id": 2, "sheet_number": "A-101"},
        {"id": 3, "sheet_number": "S-101"},
    ]
    groups = group_by_discipline(sheets)
    # Structural before Architectural before Electrical (S, A, E order)
    assert [g["discipline"] for g in groups] == ["S", "A", "E"]


def test_sheets_natural_sorted_within_group():
    sheets = [
        {"id": 1, "sheet_number": "A-10"},
        {"id": 2, "sheet_number": "A-2"},
        {"id": 3, "sheet_number": "A-1"},
    ]
    groups = group_by_discipline(sheets)
    order = [s["sheet_number"] for s in groups[0]["sheets"]]
    assert order == ["A-1", "A-2", "A-10"]   # natural, not lexical (A-10 last)


def test_explicit_discipline_field_wins_over_derived():
    sheets = [{"id": 1, "sheet_number": "A-101", "discipline": "M"}]
    groups = group_by_discipline(sheets)
    assert groups[0]["discipline"] == "M"


def test_unknown_discipline_grouped_as_other_last():
    sheets = [
        {"id": 1, "sheet_number": "A-101"},
        {"id": 2, "sheet_number": "101"},        # no prefix -> Other
    ]
    groups = group_by_discipline(sheets)
    assert groups[-1]["discipline"] == "OTHER"
    assert groups[-1]["name"] == "Other"
    assert groups[-1]["count"] == 1


def test_group_counts_and_shape():
    sheets = [{"id": 1, "sheet_number": "A-1"}, {"id": 2, "sheet_number": "A-2"}]
    groups = group_by_discipline(sheets)
    assert len(groups) == 1 and groups[0]["count"] == 2
    assert set(groups[0]) == {"discipline", "name", "count", "sheets"}
