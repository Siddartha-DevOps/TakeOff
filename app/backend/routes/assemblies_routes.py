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
from estimating.persistence import (
    assembly_to_dict,
    cost_book_to_dict,
    seed_rows_from_library,
)
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
    cost_book_id: Optional[int] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Assemblies estimate for a drawing's latest takeoff (org-isolated).

    ``cost_book_id`` optionally prices the estimate with one of the org's saved
    cost books; without it, quantities are returned at zero cost.
    """
    cost_book = None
    if cost_book_id is not None:
        book = (
            db.query(models.CostBook)
            .filter(models.CostBook.id == cost_book_id,
                    models.CostBook.organization_id == current_user.organization_id)
            .first()
        )
        if not book:
            raise HTTPException(status_code=404, detail="Cost book not found")
        from estimating.persistence import cost_book_to_map
        cost_book = cost_book_to_map(book)

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


# ──────────────────────────────────────────────────────────────
# Persisted, org-editable assemblies (custom, on top of the code library)
# ──────────────────────────────────────────────────────────────
class ComponentIn(BaseModel):
    item: str
    unit: str
    factor: float
    waste_pct: float = 0.0
    trade: Optional[str] = None


class AssemblyIn(BaseModel):
    key: str
    name: str
    trade: str
    driver_unit: str
    components: list[ComponentIn]


def _apply_components(assembly: "models.Assembly", components: list) -> None:
    assembly.components = [
        models.AssemblyComponent(item=c.item, unit=c.unit, factor=c.factor,
                                 waste_pct=c.waste_pct, trade=c.trade)
        for c in components
    ]


@router.get("/assemblies/custom")
async def list_custom_assemblies(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """This org's persisted assemblies (editable, on top of the code library)."""
    rows = (
        db.query(models.Assembly)
        .filter(models.Assembly.organization_id == current_user.organization_id)
        .order_by(models.Assembly.key)
        .all()
    )
    return {"assemblies": [assembly_to_dict(a) for a in rows]}


@router.post("/assemblies/seed")
async def seed_assemblies(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Seed this org's assemblies from the code library (skips keys it already has)."""
    existing = {
        a.key for a in db.query(models.Assembly.key)
        .filter(models.Assembly.organization_id == current_user.organization_id).all()
    }
    created = 0
    for row in seed_rows_from_library():
        if row["key"] in existing:
            continue
        asm = models.Assembly(
            organization_id=current_user.organization_id,
            key=row["key"], name=row["name"], trade=row["trade"],
            driver_unit=row["driver_unit"],
            components=[models.AssemblyComponent(**c) for c in row["components"]],
        )
        db.add(asm)
        created += 1
    db.commit()
    return {"seeded": created, "skipped": len(existing)}


@router.post("/assemblies/custom")
async def create_assembly(
    body: AssemblyIn,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a custom assembly for this org (key must be unique per org)."""
    dup = (
        db.query(models.Assembly)
        .filter(models.Assembly.organization_id == current_user.organization_id,
                models.Assembly.key == body.key)
        .first()
    )
    if dup:
        raise HTTPException(status_code=409, detail=f"Assembly key '{body.key}' already exists")
    asm = models.Assembly(
        organization_id=current_user.organization_id,
        key=body.key, name=body.name, trade=body.trade, driver_unit=body.driver_unit,
    )
    _apply_components(asm, body.components)
    db.add(asm)
    db.commit()
    db.refresh(asm)
    return assembly_to_dict(asm)


def _own_assembly(assembly_id: int, current_user, db) -> "models.Assembly":
    asm = (
        db.query(models.Assembly)
        .filter(models.Assembly.id == assembly_id,
                models.Assembly.organization_id == current_user.organization_id)
        .first()
    )
    if not asm:
        raise HTTPException(status_code=404, detail="Assembly not found")
    return asm


@router.put("/assemblies/custom/{assembly_id}")
async def update_assembly(
    assembly_id: int,
    body: AssemblyIn,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Replace a custom assembly's fields + components."""
    asm = _own_assembly(assembly_id, current_user, db)
    asm.key, asm.name, asm.trade, asm.driver_unit = body.key, body.name, body.trade, body.driver_unit
    _apply_components(asm, body.components)
    db.commit()
    db.refresh(asm)
    return assembly_to_dict(asm)


@router.delete("/assemblies/custom/{assembly_id}")
async def delete_assembly(
    assembly_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db.delete(_own_assembly(assembly_id, current_user, db))
    db.commit()
    return {"deleted": assembly_id}


# ──────────────────────────────────────────────────────────────
# Cost books (org-scoped unit-price lists)
# ──────────────────────────────────────────────────────────────
class CostItemIn(BaseModel):
    item: str
    unit: Optional[str] = None
    unit_cost: float = 0.0


class CostBookIn(BaseModel):
    name: str
    currency: str = "USD"
    is_default: bool = False
    items: list[CostItemIn] = []


def _apply_cost_items(book: "models.CostBook", items: list) -> None:
    book.items = [
        models.CostItem(item=i.item, unit=i.unit, unit_cost=i.unit_cost) for i in items
    ]


@router.get("/cost-books")
async def list_cost_books(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(models.CostBook)
        .filter(models.CostBook.organization_id == current_user.organization_id)
        .order_by(models.CostBook.name)
        .all()
    )
    return {"cost_books": [cost_book_to_dict(b) for b in rows]}


@router.post("/cost-books")
async def create_cost_book(
    body: CostBookIn,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    book = models.CostBook(
        organization_id=current_user.organization_id,
        name=body.name, currency=body.currency, is_default=body.is_default,
    )
    _apply_cost_items(book, body.items)
    db.add(book)
    db.commit()
    db.refresh(book)
    return cost_book_to_dict(book)


def _own_cost_book(cost_book_id: int, current_user, db) -> "models.CostBook":
    book = (
        db.query(models.CostBook)
        .filter(models.CostBook.id == cost_book_id,
                models.CostBook.organization_id == current_user.organization_id)
        .first()
    )
    if not book:
        raise HTTPException(status_code=404, detail="Cost book not found")
    return book


@router.put("/cost-books/{cost_book_id}")
async def update_cost_book(
    cost_book_id: int,
    body: CostBookIn,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    book = _own_cost_book(cost_book_id, current_user, db)
    book.name, book.currency, book.is_default = body.name, body.currency, body.is_default
    _apply_cost_items(book, body.items)
    db.commit()
    db.refresh(book)
    return cost_book_to_dict(book)


@router.delete("/cost-books/{cost_book_id}")
async def delete_cost_book(
    cost_book_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db.delete(_own_cost_book(cost_book_id, current_user, db))
    db.commit()
    return {"deleted": cost_book_id}
