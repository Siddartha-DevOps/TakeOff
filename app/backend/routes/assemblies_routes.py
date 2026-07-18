"""
TakeOff.ai — Trade assemblies API.

Exposes the assemblies library + expansion engine (estimating/assemblies.py):
list the available assemblies, and expand a set of measured quantities into a
priced, trade-rolled estimate. The math is pure and unit-tested; this layer only
validates input and shapes the response.
"""

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

import models
from auth import get_current_user
from estimating.assemblies import ASSEMBLY_LIBRARY, expand_takeoff

router = APIRouter(prefix="/estimating", tags=["Estimating"])


def _assembly_to_dict(asm) -> dict:
    return {
        "key": asm.key,
        "name": asm.name,
        "trade": asm.trade,
        "driver_unit": asm.driver_unit,
        "components": [
            {"item": c.item, "unit": c.unit, "factor": c.factor,
             "waste_pct": c.waste_pct, "trade": c.trade or asm.trade}
            for c in asm.components
        ],
    }


@router.get("/assemblies")
async def list_assemblies(current_user: models.User = Depends(get_current_user)):
    """The seed assemblies library (each: driver unit + component line items)."""
    return {"assemblies": [_assembly_to_dict(a) for a in ASSEMBLY_LIBRARY.values()]}


class MeasuredItem(BaseModel):
    assembly: str
    quantity: float


class ExpandRequest(BaseModel):
    measured: list[MeasuredItem]
    cost_book: Optional[dict] = None


@router.post("/assemblies/expand")
async def expand(body: ExpandRequest, current_user: models.User = Depends(get_current_user)):
    """Expand measured quantities into priced line items rolled up by trade.

    Body: ``{measured: [{assembly, quantity}], cost_book: {item: unit_cost}}``.
    Returns ``{line_items, by_trade, total, skipped}``.
    """
    measured = [m.model_dump() for m in body.measured]
    return expand_takeoff(measured, cost_book=body.cost_book)
