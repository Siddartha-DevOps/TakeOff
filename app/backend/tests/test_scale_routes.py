import asyncio
import contextlib
import json
from types import SimpleNamespace

import fitz
import numpy as np
import pytest
from fastapi import HTTPException
from PIL import Image

from canonical_takeoff import normalize_annotations
from routes import scale_routes


class FakeDB:
    def __init__(self):
        self.added = []
        self.commits = 0

    def add(self, value):
        self.added.append(value)

    def commit(self):
        self.commits += 1

    def refresh(self, _value):
        pass

    def rollback(self):
        pass


def drawing(**overrides):
    values = {
        "id": 7, "project_id": 3, "file_type": "PDF", "file_path": "plan.pdf",
        "page_number": 0, "scale_ratio": None, "scale": None, "scale_source": None,
        "scale_calibrated_at": None, "scale_detection_method": None,
        "scale_confidence": None, "scale_requires_confirmation": True, "scale_dpi": None,
        "ocr_scale_ratio": None, "ocr_scale_text": None, "ocr_scale_confidence": None,
        "ocr_scale_method": None, "ocr_scale_conflict": False,
        "ocr_scale_candidates": None, "annotations_data": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_two_point_manual_calibration_persists_and_remeasures(monkeypatch):
    item = drawing()
    user = SimpleNamespace(id=5, organization_id=11)
    db = FakeDB()
    remeasured = []
    monkeypatch.setattr(scale_routes, "_get_drawing", lambda *_args: item)
    monkeypatch.setattr(scale_routes, "_remeasure_after_scale_change", lambda _db, row, uid: remeasured.append((row.scale_ratio, uid)))
    response = asyncio.run(scale_routes.calibrate_scale(
        7,
        scale_routes.CalibratePayload(
            point1=[0, 0], point2=[72, 0], render_scale=1,
            real_world_distance=8, unit="ft",
        ),
        current_user=user, db=db,
    ))
    assert response.scale_ratio == pytest.approx(96)
    assert response.detection_method == "manual_two_point"
    assert response.confidence == 1
    assert response.manual_confirmation_required is False
    assert response.plan_dpi == 72
    assert remeasured == [(pytest.approx(96), 5)]
    assert db.commits == 1


def test_manual_raster_calibration_uses_explicit_virtual_dpi(monkeypatch):
    item = drawing(file_type="PNG")
    monkeypatch.setattr(scale_routes, "_get_drawing", lambda *_args: item)
    monkeypatch.setattr(scale_routes, "_remeasure_after_scale_change", lambda *_args: None)
    response = asyncio.run(scale_routes.calibrate_scale(
        7,
        scale_routes.CalibratePayload(
            point1=[0, 0], point2=[300, 0], render_scale=1,
            real_world_distance=4, unit="ft",
        ),
        current_user=SimpleNamespace(id=5, organization_id=11), db=FakeDB(),
    ))
    assert response.scale_ratio == pytest.approx(48)
    assert response.plan_dpi == 300


def test_scale_change_recalculates_annotation_document_and_history(monkeypatch):
    old = [{"id": "line-1", "type": "line", "geometry": [[0, 0], [72, 0]]}]
    item = drawing(scale_ratio=48, scale_dpi=72, annotations_data=json.dumps(old))
    normalized = normalize_annotations(old, 48, "PDF", 72)
    projection = {"annotations": normalized}
    monkeypatch.setattr(scale_routes, "synchronize_corrected_takeoff", lambda *_args: projection)
    db = FakeDB()
    scale_routes._remeasure_after_scale_change(db, item, 5)
    assert json.loads(item.annotations_data)[0]["measuredValue"] == 4
    assert len(db.added) == 1


def test_area_quantity_changes_with_persisted_scale():
    area = [{
        "id": "room-1", "type": "area",
        "geometry": [[0, 0], [72, 0], [72, 72], [0, 72]],
    }]
    at_one_eighth = normalize_annotations(area, 96, "PDF", 72)[0]["measuredValue"]
    at_one_quarter = normalize_annotations(area, 48, "PDF", 72)[0]["measuredValue"]
    assert at_one_eighth == 64
    assert at_one_quarter == 16


def test_raster_dpi_is_read_from_metadata_and_never_defaulted(tmp_path):
    with_dpi = tmp_path / "with-dpi.png"
    without_dpi = tmp_path / "without-dpi.png"
    Image.new("RGB", (20, 20), "white").save(with_dpi, dpi=(150, 150))
    Image.new("RGB", (20, 20), "white").save(without_dpi)
    assert scale_routes._raster_dpi(str(with_dpi)) == pytest.approx(150, abs=0.1)
    assert scale_routes._raster_dpi(str(without_dpi)) is None


def test_accept_rejects_conflicting_scale_candidates(monkeypatch):
    item = drawing(ocr_scale_ratio=100, ocr_scale_conflict=True)
    monkeypatch.setattr(scale_routes, "_get_drawing", lambda *_args: item)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(scale_routes.accept_scale_suggestion(
            7, current_user=SimpleNamespace(id=5, organization_id=11), db=FakeDB()
        ))
    assert exc.value.status_code == 409


def test_raster_ocr_without_dpi_requires_manual_calibration(monkeypatch):
    item = drawing(
        file_type="PNG", ocr_scale_ratio=100, ocr_scale_conflict=False,
        ocr_scale_method="title_block_ocr", ocr_scale_confidence=0.99,
    )
    monkeypatch.setattr(scale_routes, "_get_drawing", lambda *_args: item)
    monkeypatch.setattr(scale_routes, "_source_plan_dpi", lambda _drawing: None)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(scale_routes.accept_scale_suggestion(
            7, current_user=SimpleNamespace(id=5, organization_id=11), db=FakeDB()
        ))
    assert exc.value.status_code == 409
    assert "DPI" in exc.value.detail


def test_tenant_filter_fails_closed_when_drawing_is_not_in_organization():
    class Query:
        def join(self, *_args): return self
        def filter(self, *_args): return self
        def first(self): return None
    class DB:
        def query(self, *_args): return Query()
    with pytest.raises(HTTPException) as exc:
        scale_routes._get_drawing(7, SimpleNamespace(organization_id=99), DB())
    assert exc.value.status_code == 404


def test_object_backed_multi_page_detection_uses_exact_page(monkeypatch, tmp_path):
    path = tmp_path / "pages.pdf"
    with fitz.open() as document:
        first = document.new_page(width=612, height=792)
        first.insert_text((430, 740), "SCALE 1:50")
        second = document.new_page(width=612, height=792)
        second.insert_text((430, 740), "SCALE 1:100")
        document.save(path)

    @contextlib.contextmanager
    def materialize(uri):
        assert uri.startswith("s3://")
        yield str(path)

    monkeypatch.setattr(scale_routes.storage, "resolve_local_path", materialize)
    monkeypatch.setattr(scale_routes, "_load_scale_image", lambda *_args, **_kwargs: np.zeros((10, 10, 3), dtype=np.uint8))
    monkeypatch.setattr(scale_routes, "run_ocr_for_scale", lambda _image: None)
    page0 = scale_routes._run_ocr_suggestion(drawing(
        file_path="s3://bucket/pages.pdf", page_number=0
    ))
    page1 = scale_routes._run_ocr_suggestion(drawing(
        file_path="s3://bucket/pages.pdf", page_number=1
    ))
    assert page0["ratio"] == 50
    assert page1["ratio"] == 100
