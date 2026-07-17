"""
End-to-end smoke test: external collaboration without an account (Togal
parity — "External collaboration — unlimited, no account needed").

Runs the *real* HTTP path (FastAPI TestClient, in-process, real get_db
dependency) against a live Postgres DB — no mocks. Exercises the full
routes/share_routes.py surface, on both sides of the auth boundary:
  1. Create a VIEW-only share link (authenticated).
  2. Guest resolves the link with NO Authorization header at all —
     confirms this is genuinely unauthenticated, not just a different
     token type still checked by get_current_user.
  3. Guest can list comments and read takeoff results through the link.
  4. A VIEW-only link's guest is rejected (403) when trying to comment.
  5. Create a COMMENT-permission link; its guest can post a comment with
     just a name (no account) -- and it shows up via the *authenticated*
     /collab/ comments endpoint too, with is_guest=True.
  6. Revoking a link immediately blocks that link's guest (404), while a
     second, still-valid link for the same project keeps working.
  7. An expired link (expires_at in the past) is rejected the same way a
     revoked one is.
  8. A bogus/never-issued token gets the same 404 as a revoked one (no
     information leak about which).
  9. Cross-project: a link can't be used to reach a different project's data.
 10. Org isolation on the authenticated management endpoints: a different
     org's user can't list/revoke another org's share links.

Requires DATABASE_URL to point at a PostGIS DB with `alembic upgrade head`
already applied.

    DATABASE_URL=postgresql://user:pass@localhost/takeoff_db python scripts/smoke_test_share_links.py
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import models  # noqa: E402
from auth import create_access_token, get_password_hash  # noqa: E402
from database import SessionLocal  # noqa: E402
from routes import project_routes, realtime_routes, share_routes  # noqa: E402

app = FastAPI(title="TakeOff share links (smoke test)")
app.include_router(project_routes.router, prefix="/api")
app.include_router(realtime_routes.collab_router, prefix="/api")
app.include_router(share_routes.router, prefix="/api")
app.include_router(share_routes.guest_router, prefix="/api")
client = TestClient(app)


def main() -> int:
    db = SessionLocal()
    ids = {"org": None, "org2": None, "user": None, "user2": None,
           "project": None, "project2": None, "drawing": None,
           "view_link": None, "comment_link": None, "expired_link": None}
    try:
        org = models.Organization(name="Smoke Test Org — Share Links")
        db.add(org)
        db.commit()
        db.refresh(org)
        ids["org"] = org.id

        user = models.User(
            email="smoketest-share@example.com", hashed_password=get_password_hash("smoketestpass"),
            full_name="Smoke Tester", organization_id=org.id, role=models.UserRole.ADMIN,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        ids["user"] = user.id

        project = models.Project(name="Riverside Tower", owner_id=user.id, organization_id=org.id)
        project2 = models.Project(name="Other Project", owner_id=user.id, organization_id=org.id)
        db.add_all([project, project2])
        db.commit()
        db.refresh(project)
        db.refresh(project2)
        ids["project"], ids["project2"] = project.id, project2.id

        drawing = models.Drawing(
            project_id=project.id, filename="a.pdf", original_filename="A-101.pdf",
            file_path="/tmp/does-not-exist.pdf", file_type="PDF", sheet_name="A-101 Level 1",
        )
        db.add(drawing)
        db.commit()
        db.refresh(drawing)
        ids["drawing"] = drawing.id

        result = models.TakeoffResult(drawing_id=drawing.id, quantities_data=json.dumps(
            [{"trade": "Drywall", "item": "Partition", "quantity": 500, "unit": "sf"}]
        ))
        db.add(result)
        db.commit()

        token = create_access_token(data={"sub": user.email, "user_id": user.id})
        headers = {"Authorization": f"Bearer {token}"}

        print("[1] create a VIEW-only share link (authenticated)")
        r = client.post(f"/api/projects/{project.id}/share-links", json={"permission": "view", "label": "For GC"}, headers=headers)
        assert r.status_code == 200, r.text
        view_link = r.json()
        ids["view_link"] = view_link["id"]
        assert view_link["permission"] == "view"
        print("    ok — token", view_link["token"][:12] + "...")

        print("[2] guest resolves the link with NO Authorization header at all")
        r = client.get(f"/api/guest/{view_link['token']}")  # no headers=
        assert r.status_code == 200, r.text
        info = r.json()
        assert info["project_name"] == "Riverside Tower", info
        assert info["permission"] == "view"
        assert len(info["drawings"]) == 1 and info["drawings"][0]["id"] == drawing.id
        print("    ok — genuinely unauthenticated, no account involved")

        print("[3] guest reads comments + takeoff results through the link")
        r = client.get(f"/api/guest/{view_link['token']}/comments", params={"drawing_id": drawing.id})
        assert r.status_code == 200 and r.json()["comments"] == [], r.text
        r = client.get(f"/api/guest/{view_link['token']}/drawings/{drawing.id}/results")
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "ready"
        assert r.json()["quantities_data"][0]["quantity"] == 500
        print("    ok")

        print("[4] VIEW-only link's guest is rejected (403) when trying to comment")
        r = client.post(f"/api/guest/{view_link['token']}/comments", json={
            "drawing_id": drawing.id, "x": 10, "y": 20, "body": "Looks good", "guest_name": "Alex",
        })
        assert r.status_code == 403, r.text
        print("    ok —", r.json())

        print("[5] COMMENT-permission link: guest posts with just a name, visible to the team too")
        r = client.post(f"/api/projects/{project.id}/share-links", json={"permission": "comment"}, headers=headers)
        assert r.status_code == 200, r.text
        comment_link = r.json()
        ids["comment_link"] = comment_link["id"]
        r = client.post(f"/api/guest/{comment_link['token']}/comments", json={
            "drawing_id": drawing.id, "x": 15, "y": 25, "body": "Can we widen this hallway?", "guest_name": "Alex Chen",
        })
        assert r.status_code == 200, r.text
        posted = r.json()
        assert posted["is_guest"] is True
        assert posted["display_name"] == "Alex Chen"
        assert posted["author_id"] is None
        # The authenticated team-facing comments endpoint sees it too.
        r = client.get(f"/api/collab/projects/{project.id}/comments", headers=headers)
        assert r.status_code == 200, r.text
        team_view = [c for c in r.json()["comments"] if c["id"] == posted["id"]]
        assert len(team_view) == 1 and team_view[0]["guest_name"] == "Alex Chen"
        print("    ok — guest comment visible to the authenticated team, correctly attributed")

        print("[6] revoking a link blocks its guest immediately; the other link keeps working")
        r = client.delete(f"/api/share-links/{view_link['id']}", headers=headers)
        assert r.status_code == 200, r.text
        r = client.get(f"/api/guest/{view_link['token']}")
        assert r.status_code == 404, r.text
        r = client.get(f"/api/guest/{comment_link['token']}")
        assert r.status_code == 200, "revoking one link must not affect a different, still-valid link"
        print("    ok")

        print("[7] an expired link is rejected the same way")
        expired = models.ShareLink(
            project_id=project.id, token="expired-token-1234567890", permission=models.ShareLinkPermission.VIEW,
            created_by=user.id, expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        db.add(expired)
        db.commit()
        db.refresh(expired)
        ids["expired_link"] = expired.id
        r = client.get("/api/guest/expired-token-1234567890")
        assert r.status_code == 404, r.text
        print("    ok")

        print("[8] a bogus token gets the identical 404, no information leak")
        r = client.get("/api/guest/this-token-was-never-issued")
        assert r.status_code == 404, r.text
        assert r.json()["detail"] == "This share link is invalid or has expired"
        print("    ok —", r.json())

        print("[9] a link can't reach a different project's data")
        r = client.get(f"/api/projects/{project2.id}/share-links", headers=headers)
        # (project2 has no links of its own yet -- the real check is that
        # comment_link, scoped to `project`, can't resolve project2's drawings)
        other_drawing = models.Drawing(
            project_id=project2.id, filename="b.pdf", original_filename="B-1.pdf",
            file_path="/tmp/b.pdf", file_type="PDF",
        )
        db.add(other_drawing)
        db.commit()
        db.refresh(other_drawing)
        r = client.get(f"/api/guest/{comment_link['token']}/drawings/{other_drawing.id}/results")
        assert r.status_code == 404, r.text
        print("    ok")

        print("[10] org isolation on link management")
        org2 = models.Organization(name="Smoke Test Org 2 — Share Links")
        db.add(org2)
        db.commit()
        db.refresh(org2)
        ids["org2"] = org2.id
        user2 = models.User(email="smoketest-share-2@example.com", hashed_password=get_password_hash("x"),
                             organization_id=org2.id, role=models.UserRole.ADMIN)
        db.add(user2)
        db.commit()
        db.refresh(user2)
        ids["user2"] = user2.id
        token2 = create_access_token(data={"sub": user2.email, "user_id": user2.id})
        r = client.get(f"/api/projects/{project.id}/share-links", headers={"Authorization": f"Bearer {token2}"})
        assert r.status_code == 404, r.text
        r = client.delete(f"/api/share-links/{comment_link['id']}", headers={"Authorization": f"Bearer {token2}"})
        assert r.status_code == 404, r.text
        print("    ok")

        print("\n✅ SMOKE TEST PASSED — external collaboration (share links, no account "
              "needed) works end-to-end against a real Postgres DB via the real HTTP routes.")
        return 0
    except Exception as exc:
        print(f"\n❌ SMOKE TEST FAILED: {exc}")
        raise
    finally:
        try:
            db.rollback()
            from sqlalchemy import text
            if ids["drawing"]:
                db.execute(text("DELETE FROM comments WHERE project_id=:p"), {"p": ids["project"]})
                db.execute(text("DELETE FROM takeoff_results WHERE drawing_id=:d"), {"d": ids["drawing"]})
                db.execute(text("DELETE FROM drawings WHERE project_id IN (:p1,:p2)"), {"p1": ids["project"], "p2": ids["project2"]})
            db.execute(text("DELETE FROM share_links WHERE project_id IN (:p1,:p2)"), {"p1": ids["project"] or 0, "p2": ids["project2"] or 0})
            for project_id in (ids["project"], ids["project2"]):
                if project_id:
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
