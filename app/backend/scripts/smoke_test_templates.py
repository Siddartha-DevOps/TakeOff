"""
End-to-end smoke test: classification libraries (Togal parity —
"Classification libraries — reusable templates, import/export").

Runs the *real* HTTP path (FastAPI TestClient, in-process, real get_db
dependency) against a live Postgres DB — no mocks. Exercises the full
routes/template_routes.py surface:
  1. Save a project's conditions as a named template.
  2. List org templates.
  3. Apply a template into a *different* project — new Condition rows,
     same field values, independent lifecycle from the template.
  4. Export a project's live conditions as a JSON payload.
  5. Import that JSON payload directly into another project (no saved
     template row needed).
  6. Rename a template; delete it (its items go with it; the Conditions
     it was ever applied to are untouched — they're independent copies).
  7. Org isolation: a user in a different org gets 404, not the data.

Requires DATABASE_URL to point at a PostGIS DB with `alembic upgrade head`
already applied.

    DATABASE_URL=postgresql://user:pass@localhost/takeoff_db python scripts/smoke_test_templates.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import models  # noqa: E402
from auth import create_access_token, get_password_hash  # noqa: E402
from database import SessionLocal  # noqa: E402
from routes import project_routes, template_routes  # noqa: E402

app = FastAPI(title="TakeOff classification templates (smoke test)")
app.include_router(project_routes.router, prefix="/api")
app.include_router(template_routes.router, prefix="/api")
client = TestClient(app)


def main() -> int:
    db = SessionLocal()
    ids = {"org": None, "org2": None, "user": None, "user2": None,
           "project": None, "project2": None, "project3": None, "template": None}
    try:
        org = models.Organization(name="Smoke Test Org — Templates")
        db.add(org)
        db.commit()
        db.refresh(org)
        ids["org"] = org.id

        user = models.User(
            email="smoketest-templates@example.com",
            hashed_password=get_password_hash("smoketestpass"),
            full_name="Smoke Tester", organization_id=org.id, role=models.UserRole.ADMIN,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        ids["user"] = user.id

        project = models.Project(name="Source Project", owner_id=user.id, organization_id=org.id)
        project2 = models.Project(name="Target Project", owner_id=user.id, organization_id=org.id)
        project3 = models.Project(name="Import Target", owner_id=user.id, organization_id=org.id)
        db.add_all([project, project2, project3])
        db.commit()
        db.refresh(project)
        db.refresh(project2)
        db.refresh(project3)
        ids["project"], ids["project2"], ids["project3"] = project.id, project2.id, project3.id

        c1 = models.Condition(project_id=project.id, name="Drywall - Interior", trade="Drywall",
                               annotation_type="area", unit="sf", unit_cost=4.5, waste_percent=10)
        c2 = models.Condition(project_id=project.id, name="Outlet Count", trade="Electrical",
                               annotation_type="count", unit="ea", unit_cost=45.0)
        db.add_all([c1, c2])
        db.commit()

        token = create_access_token(data={"sub": user.email, "user_id": user.id})
        headers = {"Authorization": f"Bearer {token}"}

        print("[1] save project conditions as a template")
        r = client.post(f"/api/projects/{project.id}/conditions/save-as-template",
                         json={"name": "Standard Residential", "description": "Base condition set"}, headers=headers)
        assert r.status_code == 200, r.text
        template = r.json()
        ids["template"] = template["id"]
        assert len(template["items"]) == 2, template
        assert {i["name"] for i in template["items"]} == {"Drywall - Interior", "Outlet Count"}
        print("    ok — template", template["id"], "with", len(template["items"]), "items")

        print("[2] list org templates")
        r = client.get("/api/condition-templates", headers=headers)
        assert r.status_code == 200 and any(t["id"] == template["id"] for t in r.json()), r.text
        print("    ok")

        print("[3] apply template into a DIFFERENT project")
        r = client.post(f"/api/projects/{project2.id}/conditions/apply-template/{template['id']}", headers=headers)
        assert r.status_code == 200, r.text
        applied = r.json()
        assert len(applied) == 2
        assert all(c["project_id"] == project2.id for c in applied)
        names = {c["name"] for c in applied}
        assert names == {"Drywall - Interior", "Outlet Count"}, names
        # Independent copies, not references — confirm distinct Condition ids from the source.
        applied_ids = {c["id"] for c in applied}
        source_ids = {c1.id, c2.id}
        assert applied_ids.isdisjoint(source_ids), (applied_ids, source_ids)
        print("    ok —", len(applied), "new independent Condition rows in project", project2.id)

        print("[4] export a project's live conditions as JSON")
        r = client.get(f"/api/projects/{project.id}/conditions/export", headers=headers)
        assert r.status_code == 200, r.text
        exported = r.json()
        assert len(exported["items"]) == 2, exported
        print("    ok —", exported["name"])

        print("[5] import that JSON directly into another project (no template row)")
        r = client.post(f"/api/projects/{project3.id}/conditions/import", json=exported, headers=headers)
        assert r.status_code == 200, r.text
        imported = r.json()
        assert len(imported) == 2 and all(c["project_id"] == project3.id for c in imported)
        print("    ok —", len(imported), "conditions imported into project", project3.id)

        print("[6] rename + delete the template (items go, applied Conditions untouched)")
        r = client.put(f"/api/condition-templates/{template['id']}", json={"name": "Standard Residential v2"}, headers=headers)
        assert r.status_code == 200 and r.json()["name"] == "Standard Residential v2", r.text
        r = client.delete(f"/api/condition-templates/{template['id']}", headers=headers)
        assert r.status_code == 200, r.text
        r = client.get(f"/api/condition-templates/{template['id']}", headers=headers)
        assert r.status_code == 404, r.text
        still_applied = db.query(models.Condition).filter(models.Condition.project_id == project2.id).count()
        assert still_applied == 2, still_applied
        print("    ok — template gone, the 2 Conditions it created in project", project2.id, "remain")

        print("[7] org isolation: a different org's user gets 404, not the data")
        org2 = models.Organization(name="Smoke Test Org 2 — Templates")
        db.add(org2)
        db.commit()
        db.refresh(org2)
        ids["org2"] = org2.id
        user2 = models.User(email="smoketest-templates-2@example.com", hashed_password=get_password_hash("x"),
                             organization_id=org2.id, role=models.UserRole.ADMIN)
        db.add(user2)
        db.commit()
        db.refresh(user2)
        ids["user2"] = user2.id
        token2 = create_access_token(data={"sub": user2.email, "user_id": user2.id})
        r = client.get("/api/condition-templates", headers={"Authorization": f"Bearer {token2}"})
        assert r.status_code == 200 and r.json() == [], "a different org should see zero templates, not another org's"
        print("    ok")

        print("\n✅ SMOKE TEST PASSED — classification libraries work end-to-end "
              "against a real Postgres DB via the real HTTP routes.")
        return 0
    except Exception as exc:
        print(f"\n❌ SMOKE TEST FAILED: {exc}")
        raise
    finally:
        try:
            db.rollback()
            from sqlalchemy import text
            for project_id in (ids["project"], ids["project2"], ids["project3"]):
                if project_id:
                    db.execute(text("DELETE FROM conditions WHERE project_id=:p"), {"p": project_id})
                    db.execute(text("DELETE FROM projects WHERE id=:p"), {"p": project_id})
            for user_id in (ids["user"], ids["user2"]):
                if user_id:
                    db.execute(text("DELETE FROM users WHERE id=:u"), {"u": user_id})
            for org_id in (ids["org"], ids["org2"]):
                if org_id:
                    # FK-safe even if the script failed before step 6's API
                    # delete ran (which would otherwise have cleared items
                    # via the ORM's cascade="all, delete-orphan").
                    db.execute(text(
                        "DELETE FROM condition_template_items WHERE template_id IN "
                        "(SELECT id FROM condition_templates WHERE organization_id=:o)"
                    ), {"o": org_id})
                    db.execute(text("DELETE FROM condition_templates WHERE organization_id=:o"), {"o": org_id})
                    db.execute(text("DELETE FROM organizations WHERE id=:o"), {"o": org_id})
            db.commit()
        except Exception as cleanup_err:
            print(f"[cleanup] warning: {cleanup_err}")
            db.rollback()
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
