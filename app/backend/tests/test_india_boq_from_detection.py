"""
Covers the core of the India BOQ route (routes/india_routes.py): a stored
TakeoffResult.detection_data dict -> full_estimate. The route wraps this with
org-scoped drawing lookup + query-param knobs; the pricing logic under test is
exactly what the endpoint returns.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from estimating import RateBook, full_estimate


# A detection_data blob shaped like what the app stores (summary + rooms).
_DETECTION = {
    "summary": {"rooms": 4, "doors": 8, "windows": 10, "walls": 40,
                "walls_lf": 220.0, "totalArea": 1250.0},
    "rooms": [{"id": "r1", "label": "Bedroom", "area": 150}],
    "quantities": [],
}


def test_boq_from_stored_detection():
    est = full_estimate(_DETECTION, RateBook.sample())
    # Metric quantities produced from the imperial summary.
    assert est["metric_quantities"]
    # Priced BOQ lines exist and roll up to a positive taxed grand total.
    assert est["boq"]
    s = est["summary"]
    assert s["grand_total"] > est["abstract"]["subtotal"] > 0
    assert s["gst"]["total_gst"] > 0
    assert s["currency"] == "INR"


def test_boq_inter_state_uses_igst():
    est = full_estimate(_DETECTION, RateBook.sample(), inter_state=True)
    gst = est["summary"]["gst"]
    assert gst["igst"] > 0 and gst["cgst"] == 0 and gst["sgst"] == 0


def test_boq_handles_empty_detection_gracefully():
    # No measurable summary -> no BOQ lines, zero totals, no crash.
    est = full_estimate({"summary": {}}, RateBook.sample())
    assert est["boq"] == []
    assert est["summary"]["grand_total"] == 0.0
