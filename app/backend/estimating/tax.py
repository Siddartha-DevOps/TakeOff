"""
Indian tender finalization: overheads, profit, contingency, and GST.

A priced BOQ subtotal (pre-tax; see ``boq.abstract``) is not yet a tender
figure. Indian estimates add contractor **overheads & profit** and a
**contingency**, then **GST** (goods & services tax) on top to reach the quoted
grand total. GST splits by supply type:
  - intra-state supply  -> CGST + SGST (half each of the rate)
  - inter-state supply   -> IGST (full rate)

Construction works contracts are commonly 18% GST. All amounts in INR.
"""

from __future__ import annotations

#: Default GST rate for construction works contracts.
DEFAULT_GST_RATE: float = 0.18


def _round2(x: float) -> float:
    return round(x + 1e-9, 2)


def gst_breakdown(
    taxable_amount: float,
    rate: float = DEFAULT_GST_RATE,
    inter_state: bool = False,
) -> dict:
    """Split GST on a taxable amount into CGST/SGST (intra) or IGST (inter)."""
    if taxable_amount < 0:
        raise ValueError("taxable_amount must be non-negative")
    if rate < 0:
        raise ValueError("rate must be non-negative")
    total = _round2(taxable_amount * rate)
    if inter_state:
        return {"rate": rate, "igst": total, "cgst": 0.0, "sgst": 0.0, "total_gst": total}
    half = _round2(taxable_amount * rate / 2.0)
    # Ensure cgst + sgst == total exactly despite rounding.
    return {"rate": rate, "cgst": half, "sgst": _round2(total - half),
            "igst": 0.0, "total_gst": total}


def finalize_estimate(
    subtotal: float,
    *,
    overhead_profit_pct: float = 15.0,
    contingency_pct: float = 3.0,
    gst_rate: float = DEFAULT_GST_RATE,
    inter_state: bool = False,
    currency: str = "INR",
) -> dict:
    """Build the full tender summary from a pre-tax BOQ subtotal.

    Waterfall: subtotal -> +overheads&profit -> +contingency = taxable value
    -> +GST = grand total. Percentages are on the running base in that order.
    """
    if subtotal < 0:
        raise ValueError("subtotal must be non-negative")
    for pct in (overhead_profit_pct, contingency_pct):
        if pct < 0:
            raise ValueError("percentages must be non-negative")

    subtotal = _round2(subtotal)
    overheads = _round2(subtotal * overhead_profit_pct / 100.0)
    after_oh = _round2(subtotal + overheads)
    contingency = _round2(after_oh * contingency_pct / 100.0)
    taxable_value = _round2(after_oh + contingency)
    gst = gst_breakdown(taxable_value, rate=gst_rate, inter_state=inter_state)
    grand_total = _round2(taxable_value + gst["total_gst"])

    return {
        "currency": currency,
        "subtotal": subtotal,
        "overhead_profit_pct": overhead_profit_pct,
        "overhead_profit": overheads,
        "contingency_pct": contingency_pct,
        "contingency": contingency,
        "taxable_value": taxable_value,
        "gst": gst,
        "grand_total": grand_total,
    }
