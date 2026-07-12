"""
End-to-end smoke test: vector AUTODETECT -> PostGIS persistence -> spatial query.

Runs the *real* path against a live Postgres+PostGIS (no mocks, no HTTP):
  1. Build a synthetic vector PDF (known rooms + door symbols).
  2. Measure it with the vector engine (geometry.measure_pdf / match_symbols).
  3. Convert PDF points -> 300-DPI plan-space pixels (geometry.coords).
  4. Persist as real Detection/Measurement rows (detection_geometry).
  5. Query the rows back and run a PostGIS ST_Area on the stored geometry,
     converting px^2 -> sqft and asserting it matches the engine's sqft.

This is what proves the merged code actually executes against a real database,
not just that it compiles. Requires DATABASE_URL to point at a PostGIS DB with
`alembic upgrade head` already applied.

    DATABASE_URL=postgresql://user:pass@localhost/takeoff_db python scripts/smoke_test.py
"""

import os
import sys
import tempfile
from pathlib import Path

# Make the backend package importable when run from scripts/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fitz  # noqa: E402
from sqlalchemy import text  # noqa: E402

import models  # noqa: E402
from database import SessionLocal  # noqa: E402
from detection_geometry import persist_detection_geometries  # noqa: E402
from geometry import match_symbols, measure_pdf  # noqa: E402
from geometry.coords import bbox_to_pixels  # noqa: E402

SCALE_RATIO = 96.0  # 1/8"=1'-0"
ROOM_W_PT, ROOM_H_PT = 144.0, 72.0  # 16x8 ft = 128 sqft each
EXPECTED_ROOM_SQFT = 128.0
# sqft = px_area * (scale_ratio / (12 * REFERENCE_DPI))^2  (see Drawing3DView.jsx)
PX_TO_SQFT = (SCALE_RATIO / (12 * 300.0)) ** 2


def _make_vector_pdf(path):
    doc = fitz.open()
    page = doc.new_page(width=1000, height=800)
    for i in range(4):  # 4 rooms
        x0 = 60 + (i % 2) * (ROOM_W_PT + 40)
        y0 = 60 + (i // 2) * (ROOM_H_PT + 40)
        page.draw_rect(fitz.Rect(x0, y0, x0 + ROOM_W_PT, y0 + ROOM_H_PT), color=(0, 0, 0), width=1)
    for i in range(3):  # 3 doors (leaf + swing arc)
        x, y = 120 + i * 130, 420
        sh = page.new_shape()
        sh.draw_line((x, y), (x + 40, y))
        sh.draw_bezier((x + 40, y), (x + 55, y + 15), (x + 55, y + 25), (x + 40, y + 40))
        sh.finish(color=(0, 0, 0), width=1)
        sh.commit()
    doc.save(str(path))
    doc.close()


def main() -> int:
    db = SessionLocal()
    ids = {"org": None, "user": None, "project": None, "drawing": None}
    try:
        # ── 1-3. engine + coordinate conversion ────────────────────
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
            pdf_path = tf.name
        _make_vector_pdf(pdf_path)

        # min_room_sqft filters out sub-threshold closed faces (e.g. door
        # swing-arcs enclose ~13 sqft), leaving the four real rooms.
        measure = measure_pdf(pdf_path, SCALE_RATIO, min_room_sqft=50.0)
        assert measure is not None, "measure_pdf returned None on a vector PDF"
        symbols = match_symbols(pdf_path)
        doors = sum(g["count"] for g in symbols["groups"] if g["symbol_type"] == "door")
        print(f"[engine] rooms={len(measure['rooms'])} doors={doors} "
              f"symbol_counts={symbols['symbol_counts']}")
        assert len(measure["rooms"]) == 4, [r["area"] for r in measure["rooms"]]
        assert doors == 3, doors

        det_px = {"rooms": [], "doors": [], "windows": [], "mep": []}
        for room in measure["rooms"]:
            det_px["rooms"].append({
                "id": room["id"], "label": room["label"],
                "bbox": bbox_to_pixels(room["bbox"]),
                "area": room["area"], "confidence": room["confidence"],
            })
        # Persist only real symbol types (door/window/fixture); the generic
        # "symbol" cluster on this fixture is the room rectangles themselves.
        layer = {"door": "doors", "window": "windows", "fixture": "mep"}
        for g in symbols["groups"]:
            if g["symbol_type"] not in layer:
                continue
            for inst in g["instances"]:
                det_px[layer[g["symbol_type"]]].append({
                    "id": inst["id"], "type": g["symbol_type"],
                    "bbox": bbox_to_pixels(inst["bbox"]), "confidence": 1.0,
                })

        # ── 4. minimal object graph + persist ──────────────────────
        org = models.Organization(name="SmokeTest Org")
        db.add(org); db.flush(); ids["org"] = org.id
        user = models.User(email=f"smoke_{org.id}@test.local", hashed_password="x", organization_id=org.id)
        db.add(user); db.flush(); ids["user"] = user.id
        project = models.Project(name="SmokeTest Project", owner_id=user.id, organization_id=org.id)
        db.add(project); db.flush(); ids["project"] = project.id
        drawing = models.Drawing(
            project_id=project.id, filename="smoke.pdf", original_filename="smoke.pdf",
            file_path=pdf_path, file_type="PDF", page_number=0,
        )
        db.add(drawing); db.commit(); ids["drawing"] = drawing.id

        created = persist_detection_geometries(db, project.id, drawing.id, det_px, source="vector")
        print(f"[persist] created {created} Detection rows")
        assert created == 4 + 3, f"expected 7 detections (4 rooms + 3 doors), got {created}"

        # ── 5. read back + PostGIS spatial query ───────────────────
        n_det = db.query(models.Detection).filter_by(drawing_id=drawing.id).count()
        n_meas = db.query(models.Measurement).join(models.Detection).filter(
            models.Detection.drawing_id == drawing.id).count()
        print(f"[db] detections={n_det} measurements={n_meas}")
        assert n_det == 7 and n_meas == 7

        # ST_Area on the stored geometry, in the DB, for one room -> sqft.
        px_area = db.execute(text(
            "SELECT ST_Area(geom) FROM detections "
            "WHERE drawing_id=:d AND annotation_type='area' ORDER BY id LIMIT 1"
        ), {"d": drawing.id}).scalar()
        sqft = px_area * PX_TO_SQFT
        print(f"[postgis] ST_Area={px_area:.0f} px^2  ->  {sqft:.1f} sqft "
              f"(engine says {EXPECTED_ROOM_SQFT})")
        assert abs(sqft - EXPECTED_ROOM_SQFT) < 1.0, f"area mismatch: {sqft} vs {EXPECTED_ROOM_SQFT}"

        print("\n✅ SMOKE TEST PASSED — vector AUTODETECT persists to PostGIS and "
              "ST_Area on the stored geometry matches the engine's measurement.")
        return 0
    except Exception as exc:
        print(f"\n❌ SMOKE TEST FAILED: {exc}")
        raise
    finally:
        # FK-safe teardown in child -> parent order (no ON DELETE CASCADE on
        # these FKs, so bulk-deleting a parent first would violate them).
        try:
            db.rollback()
            if ids["drawing"]:
                db.execute(text("DELETE FROM measurements WHERE detection_id IN "
                                "(SELECT id FROM detections WHERE drawing_id=:d)"), {"d": ids["drawing"]})
                db.execute(text("DELETE FROM detections WHERE drawing_id=:d"), {"d": ids["drawing"]})
                db.execute(text("DELETE FROM drawings WHERE id=:d"), {"d": ids["drawing"]})
            if ids["project"]:
                db.execute(text("DELETE FROM projects WHERE id=:p"), {"p": ids["project"]})
            if ids["user"]:
                db.execute(text("DELETE FROM users WHERE id=:u"), {"u": ids["user"]})
            if ids["org"]:
                db.execute(text("DELETE FROM organizations WHERE id=:o"), {"o": ids["org"]})
            db.commit()
        except Exception as cleanup_err:
            print(f"[cleanup] warning: {cleanup_err}")
            db.rollback()
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
