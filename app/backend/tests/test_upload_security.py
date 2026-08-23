import pytest
import storage

from upload_security import (
    DEFAULT_MAX_UPLOAD_BYTES,
    UploadValidationError,
    max_upload_bytes,
    validate_file_signature,
    validate_upload_metadata,
)


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [("plan.pdf", "application/pdf"), ("plan.PNG", "image/png"), ("plan.jpeg", "image/jpeg")],
)
def test_metadata_accepts_supported_matching_types(filename, content_type):
    assert validate_upload_metadata(filename, content_type)


def test_metadata_rejects_extension_mime_mismatch():
    with pytest.raises(UploadValidationError, match="do not match"):
        validate_upload_metadata("plan.pdf", "image/png")


def test_metadata_rejects_executable_extension():
    with pytest.raises(UploadValidationError, match="not allowed"):
        validate_upload_metadata("payload.exe", "application/octet-stream")


@pytest.mark.parametrize(
    ("filename", "prefix"),
    [
        ("plan.pdf", b"%PDF-1.7 rest"),
        ("plan.png", b"\x89PNG\r\n\x1a\nrest"),
        ("plan.jpg", b"\xff\xd8\xffrest"),
        ("plan.tiff", b"II*\x00rest"),
    ],
)
def test_magic_signatures_accept_real_file_headers(filename, prefix):
    validate_file_signature(filename, prefix)


def test_magic_signature_rejects_spoofed_pdf():
    with pytest.raises(UploadValidationError, match="contents"):
        validate_file_signature("plan.pdf", b"<script>alert(1)</script>")


def test_upload_limit_is_configurable_and_invalid_values_are_safe(monkeypatch):
    monkeypatch.setenv("UPLOAD_MAX_BYTES", "12345")
    assert max_upload_bytes() == 12345
    monkeypatch.setenv("UPLOAD_MAX_BYTES", "not-a-number")
    assert max_upload_bytes() == DEFAULT_MAX_UPLOAD_BYTES


def test_production_requires_durable_object_storage_by_default(monkeypatch):
    monkeypatch.delenv("REQUIRE_OBJECT_STORAGE", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert storage.object_storage_required() is True
    monkeypatch.setenv("ENVIRONMENT", "development")
    assert storage.object_storage_required() is False
