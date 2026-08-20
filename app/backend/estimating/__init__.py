"""
TakeOff.ai — Indian estimating layer (the moat Togal.ai lacks).

Togal stops at measured quantities. In India the deliverable is a **BOQ (Bill
of Quantities)** priced against a government **Schedule of Rates** (CPWD DSR /
state PWD SOR), with **rate analysis** (labour + material + plant + overhead)
and **GST**. This package turns metric quantities (see
``geometry.india_units``) into that BOQ.

Pure Python — no GPU, model, or DB dependency — so it is fast and fully
unit-tested (``tests/test_estimating.py``).
"""

from .ratebook import RateItem, RateBook
from .boq import BOQItem, build_boq, rate_analysis, abstract, DEFAULT_ITEM_MAP
from .tax import gst_breakdown, finalize_estimate, DEFAULT_GST_RATE
from .estimate import full_estimate
from .export import boq_to_excel, boq_to_pdf

__all__ = [
    "RateItem",
    "RateBook",
    "BOQItem",
    "build_boq",
    "rate_analysis",
    "abstract",
    "DEFAULT_ITEM_MAP",
    "gst_breakdown",
    "finalize_estimate",
    "DEFAULT_GST_RATE",
    "full_estimate",
    "boq_to_excel",
    "boq_to_pdf",
]
