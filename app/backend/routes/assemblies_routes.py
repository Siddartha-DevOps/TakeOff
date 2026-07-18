"""
TakeOff.ai — Trade assemblies API.

Exposes the assemblies library + expansion engine (estimating/assemblies.py):
list the available assemblies, and expand a set of measured quantities into a
priced, trade-rolled estimate. The math is pure and unit-tested; this layer only
validates input and shapes the response.
"""

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

import models
from auth import get_current_user
from database import get_db
from estimating.assemblies import ASSEMBLY_LIBRARY, expand_takeoff
from estimating.takeoff_map import estimate_from_takeoff

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


class FromTakeoffRequest(BaseModel):
    quantities: list[dict]                 # [{trade, item, quantity, unit}]
    cost_book: Optional[dict] = None


@router.post("/assemblies/from-takeoff")
async def from_takeoff(body: FromTakeoffRequest, current_user: models.User = Depends(get_current_user)):
    """Auto-map measured takeoff quantities → assemblies → priced estimate.

    Returns ``{drivers, measured, line_items, by_trade, total, skipped}`` — the
    drivers/measured show exactly what was auto-detected and expanded.
    """
    return estimate_from_takeoff(body.quantities, cost_book=body.cost_book)


@router.get("/drawings/{drawing_id}/assemblies")
async def drawing_assemblies(
    drawing_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Assemblies estimate for a drawing's latest takeoff (org-isolated)."""
    drawing = (
        db.query(models.Drawing)
        .join(models.Project)
        .filter(
            models.Drawing.id == drawing_id,
            models.Project.organization_id == current_user.organization_id,
        )
        .first()
    )
    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")

    result = (
        db.query(models.TakeoffResult)
        .filter(models.TakeoffResult.drawing_id == drawing_id)
        .order_by(models.TakeoffResult.created_at.desc())
        .first()
    )
    if not result or not result.quantities_data:
        raise HTTPException(status_code=409, detail="No takeoff quantities for this drawing yet")
    try:
        quantities = json.loads(result.quantities_data)
    except (json.JSONDecodeError, TypeError):
        raise HTTPException(status_code=500, detail="Stored quantities are not valid JSON")

    return {"drawing_id": drawing_id, **estimate_from_takeoff(quantities)}
