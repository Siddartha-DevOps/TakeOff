"""
Tests for GST + tender finalization (increment #3) and the full estimate chain.
Correctness-critical: these are the numbers a contractor quotes.
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from estimating.tax import gst_breakdown, finalize_estimate
from estimating.estimate import full_estimate
from estimating.ratebook import RateBook


def _close(a, b, tol=0.01):
    return math.isclose(a, b, rel_tol=0, abs_tol=tol)


# ── GST split ───────────────────────────────────────────────────────────────
def test_gst_intra_state_splits_cgst_sgst():
    g = gst_breakdown(1000.0)  # 18% default
    assert _close(g["total_gst"], 180.0)
    assert _close(g["cgst"], 90.0)
    assert _close(g["sgst"], 90.0)
    assert g["igst"] == 0.0
    assert _close(g["cgst"] + g["sgst"], g["total_gst"])


def test_gst_inter_state_uses_igst():
    g = gst_breakdown(1000.0, inter_state=True)
    assert _close(g["igst"], 180.0)
    assert g["cgst"] == 0.0 and g["sgst"] == 0.0


def test_gst_split_ties_out_on_odd_amount():
    # Odd taxable amount: cgst+sgst must still equal total exactly.
    g = gst_breakdown(333.33)
    assert _close(g["cgst"] + g["sgst"], g["total_gst"])


def test_gst_rejects_negative():
    for bad in (lambda: gst_breakdown(-1.0), lambda: gst_breakdown(100.0, rate=-0.1)):
        try:
            bad()
            assert False, "expected ValueError"
        except ValueError:
            pass


# ── finalize waterfall ──────────────────────────────────────────────────────
def test_finalize_waterfall():
    # subtotal 100000; +15% OH = 115000; +3% cont = 118450; +18% GST = 139771
    s = finalize_estimate(100000.0, overhead_profit_pct=15.0, contingency_pct=3.0)
    assert _close(s["overhead_profit"], 15000.0)
    assert _close(s["taxable_value"], 118450.0)
    assert _close(s["gst"]["total_gst"], round(118450.0 * 0.18, 2))
    assert _close(s["grand_total"], 118450.0 + round(118450.0 * 0.18, 2))


def test_finalize_zero_percentages():
    s = finalize_estimate(50000.0, overhead_profit_pct=0.0, contingency_pct=0.0)
    assert _close(s["taxable_value"], 50000.0)
    assert _close(s["grand_total"], 59000.0)  # +18% GST


def test_finalize_rejects_negative_subtotal():
    try:
        finalize_estimate(-1.0)
        assert False
    except ValueError:
        pass


# ── full estimate chain (increments 1+2+3) ──────────────────────────────────
def test_full_estimate_chain():
    book = RateBook.sample()
    measure = {"summary": {"totalArea": 1000.0, "walls_lf": 200.0, "rooms": 4}}
    est = full_estimate(measure, book)
    assert est["edition"].startswith("SAMPLE-DSR")
    assert est["metric_quantities"]  # increment 1 output present
    assert est["boq"]                # increment 2 priced lines
    # increment 3: taxed summary with a positive grand total > subtotal.
    assert est["summary"]["grand_total"] > est["abstract"]["subtotal"] > 0
    assert est["summary"]["gst"]["total_gst"] > 0
    # grand total = taxable_value + gst
    s = est["summary"]
    assert _close(s["grand_total"], s["taxable_value"] + s["gst"]["total_gst"])
