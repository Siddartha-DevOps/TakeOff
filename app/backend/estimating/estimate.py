"""
End-to-end India estimate: measured geometry -> priced, taxed tender total.

Chains the three increments into one call a route/export can use:
  geometry (imperial)  --india_units.india_quantities-->  metric rows
                       --boq.build_boq-->                  priced BOQ lines
                       --boq.abstract-->                   chapter rollup + subtotal
                       --tax.finalize_estimate-->          +OH/profit +contingency +GST
"""

from __future__ import annotations

from geometry import india_units as iu
from .ratebook import RateBook
from .boq import build_boq, abstract
from .tax import finalize_estimate, DEFAULT_GST_RATE


def full_estimate(
    measure_result: dict,
    ratebook: RateBook,
    *,
    item_map: dict[str, str] | None = None,
    wall_height_m: float | None = None,
    overhead_profit_pct: float = 15.0,
    contingency_pct: float = 3.0,
    gst_rate: float = DEFAULT_GST_RATE,
    inter_state: bool = False,
) -> dict:
    """Produce the full Indian estimate from a geometry measurement result."""
    if wall_height_m is None:
        metric_rows = iu.india_quantities(measure_result)
    else:
        metric_rows = iu.india_quantities(measure_result, wall_height_m=wall_height_m)

    boq = build_boq(metric_rows, ratebook, item_map=item_map)
    ab = abstract(boq)
    summary = finalize_estimate(
        ab["subtotal"],
        overhead_profit_pct=overhead_profit_pct,
        contingency_pct=contingency_pct,
        gst_rate=gst_rate,
        inter_state=inter_state,
    )
    return {
        "edition": ratebook.edition,
        "metric_quantities": metric_rows,
        "boq": [b.as_dict() for b in boq],
        "abstract": ab,
        "summary": summary,
    }
