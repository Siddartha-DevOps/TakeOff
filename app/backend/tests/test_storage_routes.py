import contextlib
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest
from fastapi import BackgroundTasks, HTTPException

import models
import storage
from routes import project_routes, scale_routes, upload_routes


class FakeQuery:
    def __init__(self, result):
        self.result = result

    def join(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.result


class QueryDB:
    def __init__(self, result):
        self.result = result
        self.deleted = []
        self.commits = 0

    def query(self, *args, **kwargs):
        return FakeQuery(self.result)

    def delete(self, value):
        self.deleted.append(value)

    def commit(self):
        self.commits += 1


class IngestDB:
    def __init__(self):
        self.added = []
        self.next_id = 1

    def add(self, value):
        self.added.append(value)

    def commit(self):
        pass

    def refresh(self, value):
        if value.id is None:
            value.id = self.next_id
            self.next_id += 1


def _user(organization_id=17):
    return SimpleNamespace(id=3, organization_id=organization_id, role=models.UserRole.OWNER)


def test_presign_uses_organization_and_project_scoped_key(monkeypatch):
    project = SimpleNamespace(id=9, organization_id=17)
    db = QueryDB(project)
    captured = {}
    monkeypatch.setattr(storage, "storage_available", lambda: True)

    def fake_presign(key, content_type, max_bytes):
        captured.update(key=key, content_type=content_type, max_bytes=max_bytes)
        return {"url": "https://storage.example/upload", "fields": {"key": key}}

    monkeypatch.setattr(storage, "generate_presigned_upload", fake_presign)
    response = asyncio.run(upload_routes.presign_drawing_upload(
        9,
        upload_routes.PresignUploadRequest(filename="Floor Plan.PDF", content_type="application/pdf"),
        current_user=_user(),
        db=db,
    ))

    assert captured["key"].startswith("organizations/17/projects/9/drawings/")
    assert response["key"] == captured["key"]


def test_confirm_rejects_key_from_other_tenant_before_storage_access(monkeypatch):
    project = SimpleNamespace(id=9, organization_id=17)
    db = QueryDB(project)
    monkeypatch.setattr(storage, "storage_available", lambda: True)
    touched = []
    monkeypatch.setattr(storage, "object_head", lambda key: touched.append(key))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(upload_routes.confirm_drawing_upload(
            9,
            upload_routes.ConfirmUploadRequest(
                key="organizations/88/projects/9/drawings/stolen.pdf",
                original_filename="plan.pdf",
            ),
            BackgroundTasks(),
            current_user=_user(17),
            db=db,
        ))

    assert exc.value.status_code == 400
    assert touched == []


def test_download_returns_short_lived_signed_redirect_for_authorized_tenant(monkeypatch):
    key = "organizations/17/projects/9/drawings/plan.pdf"
    drawing = SimpleNamespace(
        id=5,
        file_path=storage.to_uri(key),
        file_type="PDF",
        original_filename="A 101.pdf",
    )
    db = QueryDB(drawing)
    monkeypatch.setattr(storage, "storage_available", lambda: True)
    monkeypatch.setattr(storage, "object_head", lambda candidate: {"ContentLength": 100})
    calls = []

    def fake_download(candidate, **kwargs):
        calls.append((candidate, kwargs))
        return "https://storage.example/private?signature=temporary"

    monkeypatch.setattr(storage, "generate_presigned_download", fake_download)
    response = asyncio.run(upload_routes.download_drawing_file(5, current_user=_user(), db=db))

    assert response.status_code in {302, 307}
    assert response.headers["location"].endswith("signature=temporary")
    assert calls == [(key, {"filename": "A 101.pdf", "content_type": "application/pdf"})]


def test_download_does_not_sign_cross_tenant_or_missing_drawing(monkeypatch):
    db = QueryDB(None)
    signed = []
    monkeypatch.setattr(storage, "generate_presigned_download", lambda *args, **kwargs: signed.append(args))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(upload_routes.download_drawing_file(99, current_user=_user(), db=db))

    assert exc.value.status_code == 404
    assert signed == []


def test_multi_page_pdf_rows_share_one_durable_reference_after_local_restart(monkeypatch, tmp_path):
    pdf_path = tmp_path / "plan-set.pdf"
    with fitz.open() as document:
        document.new_page(width=612, height=792)
        document.new_page(width=612, height=792)
        document.save(pdf_path)

    durable_uri = "s3://organizations/17/projects/9/drawings/plan-set.pdf"

    @contextlib.contextmanager
    def materialize(file_path):
        assert file_path == durable_uri
        yield str(pdf_path)

    monkeypatch.setattr(storage, "resolve_local_path", materialize)
    monkeypatch.setattr("analysis_jobs.enqueue_analysis", lambda db, drawing: None)
    db = IngestDB()
    background = BackgroundTasks()

    drawings = upload_routes.ingest_plan_set(
        db,
        background,
        organization_id=17,
        project_id=9,
        file_path=durable_uri,
        filename="opaque.pdf",
        original_filename="plan-set.pdf",
        file_size=pdf_path.stat().st_size,
        file_ext="pdf",
        sheet_name=None,
        scale=None,
    )

    assert len(drawings) == 2
    assert {drawing.page_number for drawing in drawings} == {0, 1}
    assert {drawing.total_pages for drawing in drawings} == {2}
    assert {drawing.file_path for drawing in drawings} == {durable_uri}
    assert len({drawing.upload_batch_id for drawing in drawings}) == 1


def test_malformed_multi_page_source_fails_instead_of_silently_becoming_one_page(monkeypatch, tmp_path):
    bad_pdf = tmp_path / "bad.pdf"
    bad_pdf.write_bytes(b"%PDF-not-a-real-document")

    @contextlib.contextmanager
    def materialize(_file_path):
        yield str(bad_pdf)

    monkeypatch.setattr(storage, "resolve_local_path", materialize)
    with pytest.raises(ValueError, match="Unable to read PDF page count"):
        upload_routes.ingest_plan_set(
            IngestDB(), BackgroundTasks(), 17, 9, "s3://bad.pdf", "bad.pdf", "bad.pdf",
            bad_pdf.stat().st_size, "pdf", None, None,
        )


def test_scale_ocr_materializes_object_storage_and_uses_the_correct_pdf_page(monkeypatch):
    calls = []

    @contextlib.contextmanager
    def materialize(file_path):
        assert file_path == "s3://organizations/17/projects/9/drawings/plan.pdf"
        yield "C:/temporary/materialized.pdf"

    def load_drawing(path, page_number):
        calls.append((path, page_number))
        return "image"

    monkeypatch.setattr(storage, "resolve_local_path", materialize)
    monkeypatch.setattr(scale_routes, "_load_scale_image", lambda path, file_type, page_number: load_drawing(path, page_number))
    monkeypatch.setattr(scale_routes, "extract_pdf_scale_candidates", lambda path, page: [])
    monkeypatch.setattr(scale_routes, "run_ocr_for_scale", lambda image: {
        "ratio": 96.0,
        "text": '1/8" = 1\'-0"',
        "raw_text": '1/8" = 1\'-0"',
        "confidence": 0.9,
        "method": "ocr_text",
        "candidates": [{
            "ratio": 96.0, "text": '1/8" = 1\'-0"', "confidence": 0.9,
            "method": "ocr_text", "pattern_type": "imperial_fraction",
        }],
    })
    drawing = SimpleNamespace(
        file_path="s3://organizations/17/projects/9/drawings/plan.pdf",
        page_number=3,
        file_type="PDF",
    )

    suggestion = scale_routes._run_ocr_suggestion(drawing)

    assert calls == [("C:/temporary/materialized.pdf", 3)]
    assert suggestion["ratio"] == 96.0
    assert suggestion["raw_text"] == '1/8" = 1\'-0"'


def test_tiled_artifact_is_lazily_restored_after_backend_restart(monkeypatch, tmp_path):
    destination = tmp_path / "9" / "3" / "0_0.jpg"
    seen = []
    monkeypatch.setattr(storage, "storage_available", lambda: True)
    monkeypatch.setattr(upload_routes, "_storage_head_or_http_error", lambda key: {"ContentLength": 4})

    def download(key, path):
        seen.append(key)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(b"tile")

    monkeypatch.setattr(storage, "download_file", download)
    restored = upload_routes._restore_tile_artifact(17, 9, 22, "3/0_0.jpg", destination)

    assert restored is True
    assert destination.read_bytes() == b"tile"
    assert seen == ["organizations/17/projects/9/artifacts/drawings/22/tiles/3/0_0.jpg"]


def test_project_delete_removes_shared_object_once_and_database_record(monkeypatch, tmp_path):
    shared = "s3://organizations/17/projects/9/drawings/plan-set.pdf"
    project = SimpleNamespace(
        id=9,
        owner_id=3,
        drawings=[SimpleNamespace(file_path=shared), SimpleNamespace(file_path=shared)],
    )
    db = QueryDB(project)
    deleted = []
    monkeypatch.setattr(project_routes.permissions, "can_modify_project", lambda user, candidate: True)
    monkeypatch.setattr(storage, "delete_object", lambda key: deleted.append(key))
    monkeypatch.setattr(storage, "storage_available", lambda: False)
    monkeypatch.setattr(project_routes, "_LOCAL_UPLOAD_ROOT", tmp_path)

    result = asyncio.run(project_routes.delete_project(9, current_user=_user(), db=db))

    assert deleted == ["organizations/17/projects/9/drawings/plan-set.pdf"]
    assert db.deleted == [project]
    assert db.commits == 1
    assert result == {"message": "Project deleted successfully"}


def test_project_delete_keeps_database_record_when_storage_cleanup_fails(monkeypatch, tmp_path):
    project = SimpleNamespace(
        id=9,
        owner_id=3,
        drawings=[SimpleNamespace(file_path="s3://organizations/17/projects/9/drawings/plan.pdf")],
    )
    db = QueryDB(project)
    monkeypatch.setattr(project_routes.permissions, "can_modify_project", lambda user, candidate: True)
    monkeypatch.setattr(storage, "storage_available", lambda: False)
    monkeypatch.setattr(project_routes, "_LOCAL_UPLOAD_ROOT", tmp_path)

    def fail(_key):
        raise storage.StorageOperationError("provider unavailable")

    monkeypatch.setattr(storage, "delete_object", fail)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(project_routes.delete_project(9, current_user=_user(), db=db))

    assert exc.value.status_code == 503
    assert db.deleted == []
    assert db.commits == 0
