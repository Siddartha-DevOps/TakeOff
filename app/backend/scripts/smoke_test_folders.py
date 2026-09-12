"""
End-to-end smoke test: drawing folders & organization (Togal parity —
"Project folders & organization — color-coded, folders, sets").

Runs the *real* HTTP path (FastAPI TestClient, in-process, real get_db
dependency) against a live Postgres DB — no mocks. Exercises the full
routes/folder_routes.py surface plus Project.color:
  1. Project color persists (model create -> GET list, PUT update -> GET).
  2. Create color-coded folders, list them (sort_order then name).
  3. Rename/recolor a folder.
  4. Assign a drawing to a folder.
  5. Reject assigning a drawing into a folder from a *different* project.
  6. Delete a folder -> its drawings are un-filed (folder_id -> NULL via
     ON DELETE SET NULL), never deleted.
  7. Org isolation: a user in a different org gets 404, not the data.

Requires DATABASE_URL to point at a PostGIS DB with `alembic upgrade head`
already applied.

    DATABASE_URL=postgresql://user:pass@localhost/takeoff_db python scripts/smoke_test_folders.py

Builds its own minimal FastAPI app (folder_routes + project_routes only) —
same pattern as scripts/_auth_app.py — rather than importing the full
server.app, so this stays runnable with a lean dependency set (fastapi +
jose + passlib) instead of pulling in server.py's whole router list
(stripe, boto3, redis/celery, aiofiles, the AI engine's mock-mode import,
...), none of which this feature touches.
"""

import sys
from pathlib import Path

# Make the backend package importable when run from scripts/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import models  # noqa: E402
from auth import create_access_token, get_password_hash  # noqa: E402
from database import SessionLocal  # noqa: E402
from routes import folder_routes, project_routes  # noqa: E402

app = FastAPI(title="TakeOff folders (smoke test)")
app.include_router(project_routes.router, prefix="/api")
app.include_router(folder_routes.router, prefix="/api")
client = TestClient(app)


def main() -> int:
    db = SessionLocal()
    ids = {"org": None, "org2": None, "user": None, "user2": None,
           "project": None, "project2": None, "drawing": None, "drawing2": None}
    try:
        org = models.Organization(name="Smoke Test Org — Folders")
        db.add(org)
        db.commit()
        db.refresh(org)
        ids["org"] = org.id

        user = models.User(
            email="smoketest-folders@example.com",
            hashed_password=get_password_hash("smoketestpass"),
            full_name="Smoke Tester",
            organization_id=org.id,
            role=models.UserRole.ADMIN,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        ids["user"] = user.id

        project = models.Project(name="Riverside Tower", owner_id=user.id, organization_id=org.id, color="#f59e0b")
        project2 = models.Project(name="Other Project", owner_id=user.id, organization_id=org.id)
        db.add_all([project, project2])
        db.commit()
        db.refresh(project)
        db.refresh(project2)
        ids["project"], ids["project2"] = project.id, project2.id

        drawing = models.Drawing(
            project_id=project.id, filename="a.pdf", original_filename="A-101.pdf",
            file_path="/tmp/a.pdf", file_type="PDF",
        )
        drawing2 = models.Drawing(
            project_id=project2.id, filename="b.pdf", original_filename="B-1.pdf",
            file_path="/tmp/b.pdf", file_type="PDF",
        )
        db.add_all([drawing, drawing2])
        db.commit()
        db.refresh(drawing)
        db.refresh(drawing2)
        ids["drawing"], ids["drawing2"] = drawing.id, drawing2.id

        token = create_access_token(data={"sub": user.email, "user_id": user.id})
        headers = {"Authorization": f"Bearer {token}"}

        print("[1] project color: model create -> GET list, PUT update -> GET")
        r = client.get("/api/projects", headers=headers)
        assert r.status_code == 200, r.text
        listed = next(p for p in r.json() if p["id"] == project.id)
        assert listed["color"] == "#f59e0b", listed
        r = client.put(f"/api/projects/{project.id}", json={"color": "#10b981"}, headers=headers)
        assert r.status_code == 200 and r.json()["color"] == "#10b981", r.text
        print("    ok")

        print("[2] create color-coded folders + list (sort_order, name)")
        r = client.post(f"/api/projects/{project.id}/folders", json={"name": "Level 1", "color": "#ef4444"}, headers=headers)
        assert r.status_code == 200, r.text
        folder1 = r.json()
        r = client.post(f"/api/projects/{project.id}/folders", json={"name": "Electrical", "color": "#3b82f6"}, headers=headers)
        assert r.status_code == 200, r.text
        r = client.get(f"/api/projects/{project.id}/folders", headers=headers)
        assert r.status_code == 200
        names = [f["name"] for f in r.json()]
        assert names == ["Electrical", "Level 1"], names
        print("    ok —", names)

        print("[3] rename + recolor a folder")
        r = client.put(f"/api/folders/{folder1['id']}", json={"name": "Level 1 - Structural", "color": "#a855f7"}, headers=headers)
        assert r.status_code == 200 and r.json()["name"] == "Level 1 - Structural" and r.json()["color"] == "#a855f7", r.text
        print("    ok")

        print("[4] assign a drawing to a folder")
        r = client.put(f"/api/drawings/{drawing.id}/folder", json={"folder_id": folder1["id"]}, headers=headers)
        assert r.status_code == 200 and r.json()["folder_id"] == folder1["id"], r.text
        print("    ok")

        print("[5] reject cross-project folder assignment")
        r = client.put(f"/api/drawings/{drawing2.id}/folder", json={"folder_id": folder1["id"]}, headers=headers)
        assert r.status_code == 400, r.text
        print("    ok —", r.json())

        print("[6] delete folder -> drawing un-filed (folder_id NULL), not deleted")
        r = client.delete(f"/api/folders/{folder1['id']}", headers=headers)
        assert r.status_code == 200, r.text
        db.refresh(drawing)
        assert drawing.folder_id is None, drawing.folder_id
        # Direct DB check, not an HTTP round-trip: reading the row back
        # through routes/upload_routes.py would pull in aiofiles/storage.py
        # for a fact ("does this row still exist") the DB itself answers.
        still_there = db.query(models.Drawing).filter(models.Drawing.id == drawing.id).first()
        assert still_there is not None, "drawing was deleted, expected ON DELETE SET NULL to un-file it instead"
        print("    ok — drawing", drawing.id, "still exists, folder_id is now", still_there.folder_id)

        print("[7] org isolation: a different org's user gets 404, not the data")
        org2 = models.Organization(name="Smoke Test Org 2 — Folders")
        db.add(org2)
        db.commit()
        db.refresh(org2)
        ids["org2"] = org2.id
        user2 = models.User(
            email="smoketest-folders-2@example.com", hashed_password=get_password_hash("x"),
            organization_id=org2.id, role=models.UserRole.ADMIN,
        )
        db.add(user2)
        db.commit()
        db.refresh(user2)
        ids["user2"] = user2.id
        token2 = create_access_token(data={"sub": user2.email, "user_id": user2.id})
        r = client.get(f"/api/projects/{project.id}/folders", headers={"Authorization": f"Bearer {token2}"})
        assert r.status_code == 404, r.text
        print("    ok —", r.json())

        print("\n✅ SMOKE TEST PASSED — drawing folders/organization work end-to-end "
              "against a real Postgres DB via the real HTTP routes.")
        return 0
    except Exception as exc:
        print(f"\n❌ SMOKE TEST FAILED: {exc}")
        raise
    finally:
        # FK-safe teardown in child -> parent order.
        try:
            db.rollback()
            from sqlalchemy import text
            for drawing_id in (ids["drawing"], ids["drawing2"]):
                if drawing_id:
                    db.execute(text("DELETE FROM drawings WHERE id=:d"), {"d": drawing_id})
            for project_id in (ids["project"], ids["project2"]):
                if project_id:
                    db.execute(text("DELETE FROM drawing_folders WHERE project_id=:p"), {"p": project_id})
                    db.execute(text("DELETE FROM projects WHERE id=:p"), {"p": project_id})
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
