"""
Unit tests for the Indian estimating layer: rate book, BOQ, rate analysis,
abstract. Pure-Python; correctness-critical (these amounts go into a tender).
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from estimating.ratebook import RateItem, RateBook
from estimating.boq import build_boq, rate_analysis, abstract, DEFAULT_ITEM_MAP
from geometry import india_units as iu


def _close(a, b, tol=0.01):
    return math.isclose(a, b, rel_tol=0, abs_tol=tol)


# ── RateItem validation ─────────────────────────────────────────────────────
def test_rateitem_components_must_tie_to_rate():
    RateItem("x", "d", "sqm", 100.0, "ch", labour=60, material=30, plant=5, overhead=5)  # ok
    try:
        RateItem("y", "d", "sqm", 100.0, "ch", labour=60, material=30, plant=5, overhead=99)
        assert False, "expected ValueError on mismatched components"
    except ValueError:
        pass


def test_rateitem_allows_zero_breakdown():
    it = RateItem("z", "d", "cum", 8000.0, "ch")  # no breakdown given
    assert it.rate == 8000.0


def test_rateitem_rejects_negative_rate():
    try:
        RateItem("n", "d", "sqm", -1.0, "ch")
        assert False
    except ValueError:
        pass


# ── RateBook ────────────────────────────────────────────────────────────────
def test_sample_book_and_lookup():
    book = RateBook.sample()
    assert len(book) == 5
    assert book.get("13.1.1").unit == "sqm"
    assert book.require("2.8.1").chapter == "Concrete Work"


def test_book_duplicate_code_rejected():
    book = RateBook()
    book.add(RateItem("a", "d", "sqm", 10, "ch"))
    try:
        book.add(RateItem("a", "d2", "sqm", 20, "ch"))
        assert False
    except ValueError:
        pass


def test_book_from_rows():
    rows = [{"code": "c1", "description": "d", "unit": "cum", "rate": 5000,
             "chapter": "Concrete", "labour": 1500, "material": 3000, "plant": 100, "overhead": 400}]
    book = RateBook.from_rows(rows, edition="TEST")
    assert book.edition == "TEST"
    assert _close(book.require("c1").material, 3000)


# ── build_boq ───────────────────────────────────────────────────────────────
def test_build_boq_prices_mapped_rows():
    book = RateBook.sample()
    rows = [{"item": "Floor area (net)", "quantity": 100.0, "unit": "sqm"}]
    boq = build_boq(rows, book)
    assert len(boq) == 1
    assert boq[0].code == "11.3.1"
    assert _close(boq[0].amount, 100.0 * 1200.0)  # 1,20,000


def test_build_boq_skips_unmapped_and_zero():
    book = RateBook.sample()
    rows = [
        {"item": "Unknown thing", "quantity": 50, "unit": "sqm"},
        {"item": "Floor area (net)", "quantity": 0, "unit": "sqm"},
    ]
    assert build_boq(rows, book) == []


def test_build_boq_skips_unit_mismatch():
    # Wall length is in running metres but brickwork rate is per cum -> skipped,
    # signalling that a length->volume conversion is still required.
    book = RateBook.sample()
    rows = [{"item": "Wall length", "quantity": 60.0, "unit": "rmt"}]
    assert build_boq(rows, book) == []


# ── rate analysis ───────────────────────────────────────────────────────────
def test_rate_analysis_breakdown_sums_to_amount():
    book = RateBook.sample()
    item = book.require("13.1.1")  # plaster, rate 250 = 120+110+5+15
    ra = rate_analysis(item, 200.0)
    assert _close(ra["labour"], 200 * 120)
    assert _close(ra["material"], 200 * 110)
    assert _close(ra["amount"], 200 * 250)
    assert _close(ra["labour"] + ra["material"] + ra["plant"] + ra["overhead"], ra["amount"])


# ── abstract rollup ─────────────────────────────────────────────────────────
def test_abstract_rolls_up_by_chapter():
    book = RateBook.sample()
    rows = [
        {"item": "Floor area (net)", "quantity": 100.0, "unit": "sqm"},   # Flooring 1,20,000
        {"item": "Ceiling area", "quantity": 100.0, "unit": "sqm"},       # Finishing 18,000
        {"item": "Cement plaster (both faces, 2.74 m ht)", "quantity": 200.0, "unit": "sqm"},  # Finishing 50,000
    ]
    boq = build_boq(rows, book)
    ab = ab_result = abstract(boq)
    chapters = {c["chapter"]: c["amount"] for c in ab["chapters"]}
    assert _close(chapters["Flooring"], 120000)
    assert _close(chapters["Finishing"], 18000 + 50000)
    assert _close(ab["subtotal"], 120000 + 18000 + 50000)
    assert ab["currency"] == "INR"


# ── integration: geometry -> metric quantities -> BOQ -> abstract ───────────
def test_end_to_end_measure_to_boq():
    book = RateBook.sample()
    measure = {"summary": {"totalArea": 1000.0, "walls_lf": 200.0, "rooms": 4}}
    metric_rows = iu.india_quantities(measure)          # increment #1
    boq = build_boq(metric_rows, book)                  # increment #2
    ab = abstract(boq)
    # Floor + ceiling priced (sqm), plaster priced (sqm); wall length skipped (rmt).
    codes = {b.code for b in boq}
    assert "11.3.1" in codes and "13.60.1" in codes and "13.1.1" in codes
    assert ab["subtotal"] > 0
