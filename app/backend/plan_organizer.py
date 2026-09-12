"""
Plan-set organization — group + order sheets by discipline.

Togal's headline "upload, auto-name, and organize hundreds of sheets in minutes":
the OCR title-block pass (ai/title_block_ocr.py) already fills
``Drawing.sheet_number`` / ``discipline`` on ingest; this turns a flat drawing
list into the organized, discipline-grouped, correctly-ordered sheet tree an
estimator navigates.

Pure (operates on drawing dicts) — unit-tested; the DB reads/writes live in
routes/plan_set_routes.py.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional

# Construction discipline codes in conventional sheet order, with display names.
DISCIPLINE_NAMES: dict = {
    "G": "General",
    "C": "Civil",
    "L": "Landscape",
    "S": "Structural",
    "A": "Architectural",
    "I": "Interiors",
    "Q": "Equipment",
    "F": "Fire Protection",
    "FP": "Fire Protection",
    "FA": "Fire Alarm",
    "P": "Plumbing",
    "M": "Mechanical",
    "E": "Electrical",
    "T": "Telecom",
}
_DISCIPLINE_ORDER = ["G", "C", "L", "S", "A", "I", "Q", "F", "FP", "FA", "P", "M", "E", "T"]

_SHEET_PREFIX_RE = re.compile(r"^\s*([A-Za-z]{1,2})")
_NAT_RE = re.compile(r"(\d+|\D+)")


def discipline_from_sheet_number(sheet_number: Optional[str]) -> Optional[str]:
    """Derive a discipline code from a sheet number's leading letters ("A-101" -> "A")."""
    if not sheet_number:
        return None
    m = _SHEET_PREFIX_RE.match(sheet_number)
    if not m:
        return None
    code = m.group(1).upper()
    if code in DISCIPLINE_NAMES:
        return code
    return code[0] if code[0] in DISCIPLINE_NAMES else code


def discipline_name(code: Optional[str]) -> str:
    return DISCIPLINE_NAMES.get((code or "").upper(), "Other")


def _natural_key(s: Optional[str]):
    """Natural sort key so 'A-2' < 'A-10' (numeric chunks compared as ints)."""
    parts = _NAT_RE.findall(s or "")
    return [(int(p) if p.isdigit() else p.lower()) for p in parts]


def _sheet_discipline(d: dict) -> str:
    return (d.get("discipline") or discipline_from_sheet_number(d.get("sheet_number")) or "Other").upper()


def group_by_discipline(drawings: Iterable[dict]) -> list[dict]:
    """Group drawing dicts by discipline, ordered conventionally, sheets sorted.

    Each drawing dict needs ``id`` and optionally ``sheet_number``, ``sheet_name``,
    ``discipline``, ``page_number``. Returns
    ``[{discipline, name, count, sheets: [...]}]`` — disciplines in construction
    order (unknown/"Other" last), sheets by natural sheet-number then page.
    """
    groups: dict = {}
    for d in drawings:
        code = _sheet_discipline(d)
        groups.setdefault(code, []).append(d)

    def group_rank(code: str) -> tuple:
        return (_DISCIPLINE_ORDER.index(code), "") if code in _DISCIPLINE_ORDER else (len(_DISCIPLINE_ORDER), code)

    out = []
    for code in sorted(groups, key=group_rank):
        sheets = sorted(
            groups[code],
            key=lambda d: (_natural_key(d.get("sheet_number")), d.get("page_number") or 0),
        )
        out.append({
            "discipline": code,
            "name": discipline_name(code),
            "count": len(sheets),
            "sheets": sheets,
        })
    return out
