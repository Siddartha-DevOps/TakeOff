"""
End-to-end smoke test: quantities breakdown (Togal parity — "Breakdowns /
multipliers — phase/floor/unit breakdowns").

Runs the *real* HTTP path (FastAPI TestClient, in-process, real get_db
dependency) against a live Postgres DB — no mocks. Sets up 3 drawings
across 2 folders ("Level 1", "Level 2") plus one unfiled drawing, each
with a real TakeoffResult.quantities_data payload, one of them a
Repeating-Groups master unit (instance_count=4), then exercises:
  1. Breakdown grouped by folder -> trade: correct nesting, correct
     per-group totals, the master unit's multiplier already applied.
  2. total_quantity_by_unit: correct grand totals, kept separate per unit
     (never a meaningless cross-unit sum).
  3. folders list: matches the project's real DrawingFolder rows.
  4. Unfiled drawing groups under "Unfiled", not dropped or errored.
  5. drawing_ids / trades filters narrow the result correctly.
  6. Org isolation: a different org's user gets 404.

Requires DATABASE_URL to point at a PostGIS DB with `alembic upgrade head`
already applied.

    DATABASE_URL=postgresql://user:pass@localhost/takeoff_db python scripts/smoke_test_breakdown.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import models  # noqa: E402
from auth import create_access_token, get_password_hash  # noqa: E402
from database import SessionLocal  # noqa: E402
from routes import export_routes, folder_routes, project_routes  # noqa: E402

app = FastAPI(title="TakeOff breakdown (smoke test)")
app.include_router(project_routes.router, prefix="/api")
app.include_router(folder_routes.router, prefix="/api")
app.include_router(export_routes.router, prefix="/api")
client = TestClient(app)


def _find_section(sections, label):
    for child in sections.get("children", []):
        if child["label"] == label:
            return child
    return None


def _leaf_total(section, trade=None):
    if trade is not None:
        section = _find_section(section, trade)
    total = 0.0
    if section.get("rows"):
        total += sum(r["quantity"] for r in section["rows"])
    for child in section.get("children", []):
        total += _leaf_total(child)
    return round(total, 4)


def main() -> int:
    db = SessionLocal()
    ids = {"org": None, "org2": None, "user": None, "user2": None, "project": None,
           "folder1": None, "folder2": None, "drawings": [], "master_unit": None}
    try:
        org = models.Organization(name="Smoke Test Org — Breakdown")
        db.add(org)
        db.commit()
        db.refresh(org)
        ids["org"] = org.id

        user = models.User(
            email="smoketest-breakdown@example.com", hashed_password=get_password_hash("smoketestpass"),
            full_name="Smoke Tester", organization_id=org.id, role=models.UserRole.ADMIN,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        ids["user"] = user.id

        project = models.Project(name="Breakdown Test Tower", owner_id=user.id, organization_id=org.id)
        db.add(project)
        db.commit()
        db.refresh(project)
        ids["project"] = project.id

        folder1 = models.DrawingFolder(project_id=project.id, name="Level 1", color="#ef4444")
        folder2 = models.DrawingFolder(project_id=project.id, name="Level 2", color="#3b82f6")
        db.add_all([folder1, folder2])
        db.commit()
        db.refresh(folder1)
        db.refresh(folder2)
        ids["folder1"], ids["folder2"] = folder1.id, folder2.id

        def make_drawing(sheet_name, folder_id, quantities):
            d = models.Drawing(
                project_id=project.id, filename="x.pdf", original_filename=f"{sheet_name}.pdf",
                file_path="/tmp/x.pdf", file_type="PDF", sheet_name=sheet_name, folder_id=folder_id,
            )
            db.add(d)
            db.commit()
            db.refresh(d)
            result = models.TakeoffResult(drawing_id=d.id, quantities_data=json.dumps(quantities))
            db.add(result)
            db.commit()
            return d

        # Level 1: two drawings, one of them a master unit (x4 repeating group).
        d1 = make_drawing("A-101 Level 1", folder1.id, [
            {"trade": "Drywall", "item": "Interior Partition", "quantity": 500, "unit": "sf"},
            {"trade": "Flooring", "item": "LVT", "quantity": 500, "unit": "sf"},
        ])
        d2 = make_drawing("A-102 Level 1 Unit A", folder1.id, [
            {"trade": "Drywall", "item": "Unit Partition", "quantity": 100, "unit": "sf"},
        ])
        master_unit = models.MasterUnit(project_id=project.id, drawing_id=d2.id, name="Unit A", instance_count=4, created_by=user.id)
        db.add(master_unit)
        db.commit()
        db.refresh(master_unit)
        ids["master_unit"] = master_unit.id

        # Level 2: one drawing.
        d3 = make_drawing("A-201 Level 2", folder2.id, [
            {"trade": "Drywall", "item": "Interior Partition", "quantity": 300, "unit": "sf"},
        ])
        # Unfiled: no folder assigned.
        d4 = make_drawing("A-901 Details", None, [
            {"trade": "Electrical", "item": "Outlet Count", "quantity": 12, "unit": "ea"},
        ])
        ids["drawings"] = [d1.id, d2.id, d3.id, d4.id]

        token = create_access_token(data={"sub": user.email, "user_id": user.id})
        headers = {"Authorization": f"Bearer {token}"}

        print("[1] breakdown grouped by folder -> trade, master-unit multiplier applied")
        r = client.get(f"/api/export/projects/{project.id}/breakdown", params={"group_by": "folder,trade"}, headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        sections = body["sections"]
        level1 = _find_section(sections, "Level 1")
        assert level1 is not None, sections
        # d1: 500 (Drywall) + 500 (Flooring). d2 (master unit x4): 100*4=400 (Drywall).
        # Level 1 Drywall total = 500 + 400 = 900.
        level1_drywall = _leaf_total(level1, "Drywall")
        assert level1_drywall == 900, f"expected 900 (500 + 100*4 multiplier), got {level1_drywall}"
        level1_flooring = _leaf_total(level1, "Flooring")
        assert level1_flooring == 500, level1_flooring
        level2 = _find_section(sections, "Level 2")
        level2_drywall = _leaf_total(level2, "Drywall")
        assert level2_drywall == 300, level2_drywall
        print("    ok — Level 1 Drywall (with x4 multiplier applied) =", level1_drywall)

        print("[2] total_quantity_by_unit: correct, unit-separated grand totals")
        totals = body["total_quantity_by_unit"]
        # sf: 500 + 500 + 400 + 300 = 1700. ea: 12.
        assert totals.get("sf") == 1700, totals
        assert totals.get("ea") == 12, totals
        print("    ok —", totals)

        print("[3] folders list matches the project's real DrawingFolder rows")
        folder_names = {f["name"] for f in body["folders"]}
        assert folder_names == {"Level 1", "Level 2"}, folder_names
        print("    ok")

        print("[4] unfiled drawing groups under 'Unfiled', not dropped")
        unfiled = _find_section(sections, "Unfiled")
        assert unfiled is not None, [c["label"] for c in sections["children"]]
        unfiled_total = _leaf_total(unfiled)
        assert unfiled_total == 12, unfiled_total
        print("    ok")

        print("[5] drawing_ids / trades filters narrow the result")
        r = client.get(f"/api/export/projects/{project.id}/breakdown",
                        params={"group_by": "trade", "trades": "Drywall", "drawing_ids": f"{d1.id},{d3.id}"}, headers=headers)
        assert r.status_code == 200, r.text
        filtered_sections = r.json()["sections"]
        # Only d1 (500 sf Drywall) and d3 (300 sf Drywall), Flooring/Electrical excluded, d2/d4 excluded.
        drywall_only = _find_section(filtered_sections, "Drywall")
        assert drywall_only is not None
        assert _leaf_total(drywall_only) == 800, _leaf_total(drywall_only)
        assert _find_section(filtered_sections, "Flooring") is None
        print("    ok")

        print("[6] org isolation: a different org's user gets 404")
        org2 = models.Organization(name="Smoke Test Org 2 — Breakdown")
        db.add(org2)
        db.commit()
        db.refresh(org2)
        ids["org2"] = org2.id
        user2 = models.User(email="smoketest-breakdown-2@example.com", hashed_password=get_password_hash("x"),
                             organization_id=org2.id, role=models.UserRole.ADMIN)
        db.add(user2)
        db.commit()
        db.refresh(user2)
        ids["user2"] = user2.id
        token2 = create_access_token(data={"sub": user2.email, "user_id": user2.id})
        r = client.get(f"/api/export/projects/{project.id}/breakdown", headers={"Authorization": f"Bearer {token2}"})
        assert r.status_code == 404, r.text
        print("    ok")

        print("\n✅ SMOKE TEST PASSED — quantities breakdown (phase/floor + repeating-group "
              "multiplier) works end-to-end against a real Postgres DB via the real HTTP routes.")
        return 0
    except Exception as exc:
        print(f"\n❌ SMOKE TEST FAILED: {exc}")
        raise
    finally:
        try:
            db.rollback()
            from sqlalchemy import text
            if ids["master_unit"]:
                db.execute(text("DELETE FROM master_units WHERE id=:m"), {"m": ids["master_unit"]})
            for drawing_id in ids["drawings"]:
                db.execute(text("DELETE FROM takeoff_results WHERE drawing_id=:d"), {"d": drawing_id})
                db.execute(text("DELETE FROM drawings WHERE id=:d"), {"d": drawing_id})
            for folder_id in (ids["folder1"], ids["folder2"]):
                if folder_id:
                    db.execute(text("DELETE FROM drawing_folders WHERE id=:f"), {"f": folder_id})
            if ids["project"]:
                db.execute(text("DELETE FROM projects WHERE id=:p"), {"p": ids["project"]})
            for user_id in (ids["user"], ids["user2"]):
                if user_id:
                    db.execute(text("DELETE FROM users WHERE id=:u"), {"u": user_id})
            for org_id in (ids["org"], ids["org2"]):
                if org_id:
                    db.execute(text("DELETE FROM organizations WHERE id=:o"), {"o": org_id})
            db.commit()
        except Exception as cleanup_err:
            print(f"[cleanup] warning: {cleanup_err}")
            db.rollback()
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
