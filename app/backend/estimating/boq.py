"""
BOQ generation: metric quantities -> priced Bill of Quantities.

Maps each measured metric quantity row (from ``geometry.india_units``) to a
Schedule-of-Rates code, prices it, and rolls the result up into the abstract/
summary a tender submission needs. Rate analysis (labour+material+plant+
overhead) is preserved per line so the BOQ is defensible.

GST and overheads/contingencies are applied in a later step (increment #3);
this module produces the pre-tax priced BOQ.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

from .ratebook import RateBook, RateItem

#: Maps the ``item`` label emitted by ``india_units.india_quantities`` to a
#: rate code in the active book. Override per project/book as needed.
DEFAULT_ITEM_MAP: dict[str, str] = {
    "Floor area (net)": "11.3.1",     # vitrified tile flooring (sqm)
    "Ceiling area": "13.60.1",        # emulsion paint on ceiling (sqm)
    "Cement plaster (both faces, 2.74 m ht)": "13.1.1",  # 12mm plaster (sqm)
    "Wall length": "4.1.1",           # brick work (priced per rmt->cum needs conv; see note)
}


@dataclass
class BOQItem:
    code: str
    description: str
    unit: str
    quantity: float
    rate: float
    amount: float
    chapter: str

    def as_dict(self) -> dict:
        return asdict(self)


def _round2(x: float) -> float:
    return round(x + 1e-9, 2)


def build_boq(
    measured_rows: list[dict],
    ratebook: RateBook,
    item_map: dict[str, str] | None = None,
    *,
    skip_unit_mismatch: bool = True,
) -> list[BOQItem]:
    """Price measured quantity rows against a rate book.

    Args:
        measured_rows: rows of ``{"item","quantity","unit",...}`` (metric).
        ratebook: the active SOR edition.
        item_map: item-label -> rate code (defaults to ``DEFAULT_ITEM_MAP``).
        skip_unit_mismatch: if True, silently skip a row whose measured unit
            doesn't match the rate's unit (e.g. rmt vs cum) instead of pricing
            it wrongly. Skipped rows are the caller's signal that a conversion
            (e.g. wall length -> masonry volume) is still needed.

    Returns:
        Priced ``BOQItem`` list (pre-tax), in input order, mapped rows only.
    """
    imap = item_map or DEFAULT_ITEM_MAP
    out: list[BOQItem] = []

    for row in measured_rows:
        label = row.get("item")
        code = imap.get(label)
        if not code:
            continue  # unmapped measured item — not in this BOQ
        rate_item: RateItem | None = ratebook.get(code)
        if rate_item is None:
            continue
        qty = float(row.get("quantity", 0) or 0)
        if qty <= 0:
            continue
        if skip_unit_mismatch and row.get("unit") != rate_item.unit:
            continue
        amount = _round2(qty * rate_item.rate)
        out.append(BOQItem(
            code=rate_item.code,
            description=rate_item.description,
            unit=rate_item.unit,
            quantity=_round2(qty),
            rate=rate_item.rate,
            amount=amount,
            chapter=rate_item.chapter,
        ))
    return out


def rate_analysis(rate_item: RateItem, quantity: float) -> dict:
    """Labour/material/plant/overhead breakdown for a quantity of an item."""
    q = float(quantity)
    return {
        "code": rate_item.code,
        "quantity": _round2(q),
        "labour": _round2(q * rate_item.labour),
        "material": _round2(q * rate_item.material),
        "plant": _round2(q * rate_item.plant),
        "overhead": _round2(q * rate_item.overhead),
        "amount": _round2(q * rate_item.rate),
    }


def abstract(boq_items: list[BOQItem]) -> dict:
    """Roll BOQ lines up by chapter into the tender abstract/summary.

    Returns per-chapter subtotals and a grand total (pre-tax).
    """
    chapters: dict[str, float] = {}
    for it in boq_items:
        chapters[it.chapter] = _round2(chapters.get(it.chapter, 0.0) + it.amount)
    grand_total = _round2(sum(chapters.values()))
    return {
        "chapters": [
            {"chapter": ch, "amount": amt}
            for ch, amt in sorted(chapters.items())
        ],
        "subtotal": grand_total,     # pre-tax; GST added in increment #3
        "currency": "INR",
    }
