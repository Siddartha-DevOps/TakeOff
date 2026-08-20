"""
Unit tests for India metric conversions + IS 1200 measurement rules.

Pure-Python (no torch/db/GPU) so they run anywhere. Correctness-critical:
these numbers flow straight into the BOQ an estimator submits in a tender.
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from geometry import india_units as iu


def _close(a, b, tol=1e-9):
    return math.isclose(a, b, rel_tol=0, abs_tol=tol)


# ── Conversions ─────────────────────────────────────────────────────────────
def test_feet_meter_roundtrip():
    assert _close(iu.feet_to_meters(1.0), 0.3048)
    assert _close(iu.meters_to_feet(iu.feet_to_meters(123.4)), 123.4, tol=1e-9)


def test_area_conversion_and_roundtrip():
    # 1 sqft = 0.09290304 sqm exactly
    assert _close(iu.sqft_to_sqm(1.0), 0.09290304)
    assert _close(iu.sqm_to_sqft(iu.sqft_to_sqm(500.0)), 500.0, tol=1e-6)


def test_points_to_metric_matches_imperial_path():
    # 1/8" = 1'-0"  → scale_ratio 96. A 72pt (=1 paper inch) line = 8 ft = 2.4384 m.
    assert _close(iu.points_to_meters(72.0, 96.0), 8 * 0.3048, tol=1e-9)
    # Area: (72pt)^2 paper = 64 sqft = 5.945... sqm
    assert _close(iu.sqpoints_to_sqmeters(72.0 * 72.0, 96.0),
                  iu.sqft_to_sqm(64.0), tol=1e-9)


# ── IS 1200 plaster deductions ──────────────────────────────────────────────
def test_plaster_no_deduction_for_small_openings():
    # Two 0.4 m² openings (below 0.5 threshold) → no deduction.
    assert _close(iu.is1200_plaster_net_area(100.0, [0.4, 0.4]), 100.0)


def test_plaster_deducts_large_openings_only():
    # 0.4 (kept) + 2.1 (deducted) + 1.0 (deducted) → 100 - 3.1 = 96.9
    assert _close(iu.is1200_plaster_net_area(100.0, [0.4, 2.1, 1.0]), 96.9)


def test_plaster_never_negative():
    assert iu.is1200_plaster_net_area(1.0, [5.0]) == 0.0


def test_plaster_threshold_is_configurable():
    # With a 1.0 m² threshold, the 0.8 opening is now exempt.
    assert _close(
        iu.is1200_plaster_net_area(50.0, [0.8, 1.5], no_deduction_threshold_sqm=1.0),
        48.5,
    )


def test_plaster_rejects_negative_gross():
    try:
        iu.is1200_plaster_net_area(-1.0, [])
        assert False, "expected ValueError"
    except ValueError:
        pass


# ── Volumes ─────────────────────────────────────────────────────────────────
def test_concrete_volume():
    assert _close(iu.concrete_volume_cum(20.0, 0.15), 3.0)


def test_brickwork_volume_net_of_openings():
    # 5m x 3m x 0.23m = 3.45 m³ gross, minus 0.5 m³ opening = 2.95 m³
    assert _close(iu.brickwork_volume_cum(5.0, 3.0, 0.23, openings_volume_cum=0.5), 2.95)


def test_brickwork_never_negative():
    assert iu.brickwork_volume_cum(1.0, 1.0, 0.1, openings_volume_cum=100.0) == 0.0


# ── measure_result → metric quantities ──────────────────────────────────────
def test_india_quantities_metric_units():
    measure = {"summary": {"totalArea": 1000.0, "walls_lf": 200.0, "rooms": 4}}
    rows = india_rows = iu.india_quantities(measure)
    units = {r["unit"] for r in rows}
    # All metric units, no imperial leakage.
    assert units <= {"sqm", "rmt", "nos"}
    floor = next(r for r in rows if r["item"] == "Floor area (net)")
    assert _close(floor["quantity"], round(iu.sqft_to_sqm(1000.0), 3))
    walls = next(r for r in rows if r["item"] == "Wall length")
    assert _close(walls["quantity"], round(iu.feet_to_meters(200.0), 3))
    spaces = next(r for r in rows if r["item"] == "Spaces")
    assert spaces["quantity"] == 4


def test_india_quantities_empty():
    assert iu.india_quantities({"summary": {}}) == []
