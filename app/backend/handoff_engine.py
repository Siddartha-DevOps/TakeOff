"""
TakeOff.ai — Estimating-handoff engine: aggregate project quantities, map
them to UPC/WBS cost codes, and render a partner-import-ready file.

Closes memory/TOGAL_PARITY_REAUDIT.md #15: "One estimating-handoff
integration (Procore/DESTINI/Ediphi-style: quantities → UPC/WBS map +
audit trail). Not an estimating engine." None of those three partners
publish a public API (confirmed absent from web docs at time of writing;
Togal's own integrations are described in the same source doc as "thin,
partner-specific... No public API"), so "integration" here means: map
quantities to the codes those tools import, in a layout close to what each
one actually documents, plus a complete audit trail of every mapping
decision and every export — not a live authenticated API push.

Column layouts are grounded in each partner's own public documentation,
not guessed:
  - Procore's Budget Import template columns are Cost Code / Cost Type /
    Description / Unit Qty / Unit of Measure / Unit Cost, where Cost Code
    must be "Division-Code" (e.g. "09-210") and match the project's Work
    Breakdown Structure (support.procore.com/products/online/user-guide/
    project-level/budget/tutorials/import-a-budget). We have no unit cost
    (no estimating engine) — that column is left blank, not fabricated.
  - Ediphi's Togal.AI integration announcement (ediphi.com/blog) states
    quantities "map automatically to Unit Price Catalog (UPC) line items,
    complete with work breakdown structure", with "a complete audit trail
    [that] shows original values, updates, and the user and timestamp for
    each change" — the audit trail requirement is modeled directly on that
    description.
  - DESTINI Estimator (Beck Technology) has no public column spec; its
    layout here is the same UPC+WBS shape as Ediphi's, since both are
    CSI-based assembly/catalog estimating tools — documented as a
    best-effort convergence, not a verified DESTINI export spec.

CSI_SEED_CATALOG below gives each of the AI pipeline's fixed trade names
(ai/spatial_reasoning.py's quantities_data trades: Flooring, Framing,
Drywall, Painting, Doors, Windows, Electrical, Plumbing) a sensible
starting WBS/UPC pair, using CSI MasterFormat 2018 division numbers — a
public numbering standard, not a proprietary cost database. It only
pre-fills the mapping UI; every value is stored per-project in
CostCodeMapping and can be freely edited or overridden, never applied
silently at export time.
"""

import csv
import io
import json
from datetime import datetime, timezone
from typing import Optional

import export_engine
import models

CSI_SEED_CATALOG = {
    "Flooring":    {"wbs_code": "09-650", "upc_code": "09.65.00-FLOOR", "description": "Resilient / carpet flooring (CSI 09 65 00 / 09 68 00)"},
    "Framing":     {"wbs_code": "06-100", "upc_code": "06.10.00-FRAME", "description": "Rough carpentry / framing (CSI 06 10 00)"},
    "Drywall":     {"wbs_code": "09-210", "upc_code": "09.21.16-DRYWALL", "description": "Gypsum board assemblies (CSI 09 21 16)"},
    "Painting":    {"wbs_code": "09-900", "upc_code": "09.90.00-PAINT", "description": "Painting and coating (CSI 09 90 00)"},
    "Doors":       {"wbs_code": "08-100", "upc_code": "08.10.00-DOOR", "description": "Doors and frames (CSI 08 10 00)"},
    "Windows":     {"wbs_code": "08-500", "upc_code": "08.50.00-WIN", "description": "Windows (CSI 08 50 00)"},
    "Electrical":  {"wbs_code": "26-050", "upc_code": "26.05.00-ELEC", "description": "Common electrical work results (CSI 26 05 00)"},
    "Plumbing":    {"wbs_code": "22-400", "upc_code": "22.40.00-PLUMB", "description": "Plumbing fixtures (CSI 22 40 00)"},
}


def aggregate_project_quantities(db, project: "models.Project", drawing_ids: Optional[list] = None) -> list[dict]:
    """
    Sums quantities across every drawing in the project by (trade, item) —
    a handoff is a project-wide bill of quantities, not a per-drawing list.
    Reuses export_engine.extract_rows so this can never diverge from what
    the rich-export feature already shows the user for the same drawings.
    """
    drawings_query = db.query(models.Drawing).filter(models.Drawing.project_id == project.id)
    if drawing_ids:
        drawings_query = drawings_query.filter(models.Drawing.id.in_(set(drawing_ids)))
    drawings = drawings_query.all()

    totals: dict[tuple, dict] = {}
    for drawing in drawings:
        for row in export_engine.extract_rows(db, drawing):
            key = (row["trade"], row["item"], row["unit"])
            if key not in totals:
                totals[key] = {"trade": row["trade"], "item": row["item"], "unit": row["unit"], "quantity": 0.0, "drawing_names": set()}
            totals[key]["quantity"] += row["quantity"]
            totals[key]["drawing_names"].add(row["drawing_name"])

    out = []
    for (trade, item, unit), agg in sorted(totals.items()):
        out.append({
            "trade": trade,
            "item": item,
            "unit": unit,
            "quantity": round(agg["quantity"], 4),
            "sheets": sorted(agg["drawing_names"]),
        })
    return out


def get_mapping_status(db, project: "models.Project", drawing_ids: Optional[list] = None) -> list[dict]:
    """
    One row per (trade, item) in the project's aggregated quantities, joined
    with any saved CostCodeMapping. Unmapped rows get a `suggested` block
    from CSI_SEED_CATALOG (or None if the trade has no seed entry) so the
    UI can pre-fill a sensible default without ever writing it to the
    database until the estimator confirms it.
    """
    quantities = aggregate_project_quantities(db, project, drawing_ids)
    mappings = {
        (m.trade, m.item): m
        for m in db.query(models.CostCodeMapping).filter(models.CostCodeMapping.project_id == project.id).all()
    }

    rows = []
    for q in quantities:
        m = mappings.get((q["trade"], q["item"]))
        rows.append({
            **q,
            "mapping_id": m.id if m else None,
            "wbs_code": m.wbs_code if m else None,
            "upc_code": m.upc_code if m else None,
            "description": m.description if m else None,
            "target_system": m.target_system.value if m else None,
            "mapped": bool(m and (m.wbs_code or m.upc_code)),
            "suggested": CSI_SEED_CATALOG.get(q["trade"]),
        })
    return rows


def _snapshot(mapping: "models.CostCodeMapping") -> dict:
    return {
        "trade": mapping.trade,
        "item": mapping.item,
        "wbs_code": mapping.wbs_code,
        "upc_code": mapping.upc_code,
        "description": mapping.description,
        "target_system": mapping.target_system.value if mapping.target_system else None,
    }


def upsert_mapping(db, project: "models.Project", user: "models.User", trade: str, item: str,
                    wbs_code: Optional[str], upc_code: Optional[str], description: Optional[str],
                    target_system: str) -> "models.CostCodeMapping":
    """
    Create or update the mapping for (project, trade, item). Always writes a
    HandoffAuditEvent with before/after snapshots — even on first creation
    (before=None) — so the full history is reconstructable from the audit
    table alone, matching Ediphi's "original values, updates, user and
    timestamp for each change" bar.
    """
    target_enum = models.HandoffTargetSystem(target_system)
    mapping = db.query(models.CostCodeMapping).filter(
        models.CostCodeMapping.project_id == project.id,
        models.CostCodeMapping.trade == trade,
        models.CostCodeMapping.item == item,
    ).first()

    before = _snapshot(mapping) if mapping else None
    action = "mapping_updated" if mapping else "mapping_created"

    if mapping is None:
        mapping = models.CostCodeMapping(
            project_id=project.id, trade=trade, item=item, created_by=user.id,
        )
        db.add(mapping)

    mapping.wbs_code = wbs_code
    mapping.upc_code = upc_code
    mapping.description = description
    mapping.target_system = target_enum
    mapping.updated_by = user.id
    db.flush()  # assign mapping.id before the audit row references it

    db.add(models.HandoffAuditEvent(
        project_id=project.id, mapping_id=mapping.id, action=action,
        target_system=target_enum,
        before=json.dumps(before) if before else None,
        after=json.dumps(_snapshot(mapping)),
        user_id=user.id,
    ))
    db.commit()
    db.refresh(mapping)
    return mapping


def delete_mapping(db, project: "models.Project", user: "models.User", mapping: "models.CostCodeMapping") -> None:
    before = _snapshot(mapping)
    db.add(models.HandoffAuditEvent(
        project_id=project.id, mapping_id=None, action="mapping_deleted",
        target_system=mapping.target_system,
        before=json.dumps(before), after=None,
        user_id=user.id,
    ))
    # Earlier audit events for this mapping (created/updated) must outlive
    # it — the audit trail records history, it doesn't get pruned when the
    # thing it describes is deleted — so detach their FK rather than
    # cascade-deleting or leaving a dangling reference that blocks the
    # DELETE below.
    db.query(models.HandoffAuditEvent).filter(
        models.HandoffAuditEvent.mapping_id == mapping.id
    ).update({"mapping_id": None})
    db.delete(mapping)
    db.commit()


_PROCORE_HEADER = ["Cost Code", "Cost Type", "Description", "Unit Qty", "Unit of Measure", "Unit Cost"]
_UPC_WBS_HEADER = ["UPC Code", "WBS Code", "Description", "Trade", "Quantity", "Unit", "Sheets"]


def render_handoff_csv(rows: list[dict], target_system: str) -> io.BytesIO:
    """
    rows: get_mapping_status()'s shape. Unmapped rows are still included,
    flagged "UNMAPPED" in their code column rather than silently dropped or
    given a fabricated code — a partial handoff must still be honest about
    what wasn't classified yet.
    """
    output = io.StringIO()
    writer = csv.writer(output)

    if target_system == "procore":
        writer.writerow(_PROCORE_HEADER)
        for r in rows:
            cost_code = r["wbs_code"] or "UNMAPPED"
            writer.writerow([cost_code, r["trade"], r["item"] if not r["description"] else r["description"], r["quantity"], r["unit"], ""])
    else:  # destini, ediphi, generic all share the UPC+WBS layout
        writer.writerow(_UPC_WBS_HEADER)
        for r in rows:
            upc = r["upc_code"] or "UNMAPPED"
            wbs = r["wbs_code"] or "UNMAPPED"
            writer.writerow([upc, wbs, r["description"] or r["item"], r["trade"], r["quantity"], r["unit"], "; ".join(r["sheets"])])

    return io.BytesIO(output.getvalue().encode("utf-8"))


def generate_handoff_export(db, project: "models.Project", user: "models.User", target_system: str,
                             drawing_ids: Optional[list] = None) -> tuple[io.BytesIO, int, int]:
    """
    Returns (file, mapped_row_count, unmapped_row_count). Always logs a
    'handoff_exported' HandoffAuditEvent — every handoff, not just every
    mapping edit, is part of the audit trail.
    """
    models.HandoffTargetSystem(target_system)  # raises ValueError on bad input
    rows = get_mapping_status(db, project, drawing_ids)
    mapped = sum(1 for r in rows if r["mapped"])
    unmapped = len(rows) - mapped

    file = render_handoff_csv(rows, target_system)

    db.add(models.HandoffAuditEvent(
        project_id=project.id, mapping_id=None, action="handoff_exported",
        target_system=models.HandoffTargetSystem(target_system),
        before=None,
        after=json.dumps({"row_count": len(rows), "mapped": mapped, "unmapped": unmapped, "at": datetime.now(timezone.utc).isoformat()}),
        user_id=user.id,
    ))
    db.commit()

    file.seek(0)
    return file, mapped, unmapped
