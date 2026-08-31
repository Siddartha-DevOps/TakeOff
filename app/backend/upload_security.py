"""Dependency-free validation rules for drawing uploads."""

import os

ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "jfif", "tiff", "tif"}
DEFAULT_MAX_UPLOAD_BYTES = 100 * 1024 * 1024

_MIME_TYPES = {
    "pdf": {"application/pdf"},
    "png": {"image/png"},
    "jpg": {"image/jpeg", "image/jpg"},
    "jpeg": {"image/jpeg", "image/jpg"},
    "jfif": {"image/jpeg", "image/jpg"},
    "tif": {"image/tiff"},
    "tiff": {"image/tiff"},
}


class UploadValidationError(ValueError):
    pass


def file_extension(filename: str) -> str:
    return filename.rsplit(".", 1)[1].lower() if "." in filename else ""


def max_upload_bytes() -> int:
    raw = os.environ.get("UPLOAD_MAX_BYTES", str(DEFAULT_MAX_UPLOAD_BYTES))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_MAX_UPLOAD_BYTES
    return value if value > 0 else DEFAULT_MAX_UPLOAD_BYTES


def validate_upload_metadata(filename: str, content_type: str | None) -> str:
    if not filename or len(filename) > 255:
        raise UploadValidationError("Filename must be between 1 and 255 characters")
    if any(character in filename for character in ("/", "\\", "\x00", "\r", "\n")):
        raise UploadValidationError("Filename must not contain paths or control characters")
    ext = file_extension(filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise UploadValidationError(
            f"File type not allowed. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    if normalized and normalized != "application/octet-stream" and normalized not in _MIME_TYPES[ext]:
        raise UploadValidationError("File extension and content type do not match")
    return ext


def validate_file_signature(filename: str, prefix: bytes) -> None:
    ext = file_extension(filename)
    valid = {
        "pdf": prefix.startswith(b"%PDF-"),
        "png": prefix.startswith(b"\x89PNG\r\n\x1a\n"),
        "jpg": prefix.startswith(b"\xff\xd8\xff"),
        "jpeg": prefix.startswith(b"\xff\xd8\xff"),
        "jfif": prefix.startswith(b"\xff\xd8\xff"),
        "tif": prefix.startswith((b"II*\x00", b"MM\x00*")),
        "tiff": prefix.startswith((b"II*\x00", b"MM\x00*")),
    }.get(ext, False)
    if not valid:
        raise UploadValidationError("File contents do not match the declared file type")
