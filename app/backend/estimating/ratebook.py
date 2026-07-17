"""
Schedule-of-Rates rate book (CPWD DSR / state PWD SOR).

An Indian BOQ prices each measured item against an official rate from the active
Schedule of Rates edition. Each rate breaks down into **labour + material +
plant + overhead** (this is the "rate analysis" a tender requires). The official
DSR is large and its rates are edition/region specific, so this module ships a
schema + loader (CSV/rows) plus a small, clearly-labelled **sample** book for
tests and demos. Load a real DSR/SOR edition via ``RateBook.from_rows``.

Amounts are in INR. Rates here are illustrative sample values, NOT official
CPWD DSR figures — always load the active edition for real estimates.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RateItem:
    """One Schedule-of-Rates line.

    ``rate`` is the composite unit rate (INR per ``unit``). The four components
    are the rate-analysis breakdown and should sum to ``rate`` (validated).
    """

    code: str
    description: str
    unit: str            # 'sqm' | 'cum' | 'rmt' | 'nos'
    rate: float          # composite INR / unit
    chapter: str         # DSR chapter, e.g. "Concrete Work"
    labour: float = 0.0
    material: float = 0.0
    plant: float = 0.0
    overhead: float = 0.0

    def __post_init__(self) -> None:
        if self.rate < 0:
            raise ValueError(f"{self.code}: rate must be non-negative")
        comp = self.labour + self.material + self.plant + self.overhead
        # Allow a book to omit the breakdown (all zero); otherwise it must tie
        # out to the composite rate within a paisa-level tolerance.
        if comp > 0 and abs(comp - self.rate) > 0.01:
            raise ValueError(
                f"{self.code}: rate-analysis components {comp:.2f} "
                f"!= composite rate {self.rate:.2f}"
            )


class RateBook:
    """A lookup of ``code -> RateItem`` for one SOR edition."""

    def __init__(self, items: list[RateItem] | None = None, edition: str = "custom"):
        self.edition = edition
        self._by_code: dict[str, RateItem] = {}
        for it in items or []:
            self.add(it)

    def add(self, item: RateItem) -> None:
        if item.code in self._by_code:
            raise ValueError(f"duplicate rate code: {item.code}")
        self._by_code[item.code] = item

    def get(self, code: str) -> RateItem | None:
        return self._by_code.get(code)

    def require(self, code: str) -> RateItem:
        it = self._by_code.get(code)
        if it is None:
            raise KeyError(f"rate code not in book '{self.edition}': {code}")
        return it

    def __len__(self) -> int:
        return len(self._by_code)

    @classmethod
    def from_rows(cls, rows: list[dict], edition: str = "custom") -> "RateBook":
        """Build from row dicts (e.g. parsed CSV of a real DSR/SOR edition)."""
        items = [
            RateItem(
                code=str(r["code"]).strip(),
                description=str(r["description"]).strip(),
                unit=str(r["unit"]).strip(),
                rate=float(r["rate"]),
                chapter=str(r.get("chapter", "")).strip(),
                labour=float(r.get("labour", 0) or 0),
                material=float(r.get("material", 0) or 0),
                plant=float(r.get("plant", 0) or 0),
                overhead=float(r.get("overhead", 0) or 0),
            )
            for r in rows
        ]
        return cls(items, edition=edition)

    @classmethod
    def sample(cls) -> "RateBook":
        """A tiny CPWD-DSR-*style* book for tests/demos (illustrative rates)."""
        return cls(
            edition="SAMPLE-DSR (illustrative, not official)",
            items=[
                RateItem("2.8.1", "Cement concrete 1:2:4, RCC slab", "cum", 8000.0,
                         "Concrete Work", labour=2400.0, material=5000.0, plant=200.0, overhead=400.0),
                RateItem("4.1.1", "Brick work in CM 1:6, superstructure", "cum", 6500.0,
                         "Brick Work", labour=2500.0, material=3550.0, plant=100.0, overhead=350.0),
                RateItem("13.1.1", "12mm cement plaster 1:6", "sqm", 250.0,
                         "Finishing", labour=120.0, material=110.0, plant=5.0, overhead=15.0),
                RateItem("11.3.1", "Vitrified tile flooring", "sqm", 1200.0,
                         "Flooring", labour=300.0, material=830.0, plant=10.0, overhead=60.0),
                RateItem("13.60.1", "Acrylic emulsion paint, 2 coats", "sqm", 180.0,
                         "Finishing", labour=90.0, material=75.0, plant=0.0, overhead=15.0),
            ],
        )
