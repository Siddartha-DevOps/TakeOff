"""
TakeOff.ai — Object storage (S3 / Cloudflare R2), presigned uploads/downloads.

Closes memory/TOGAL_PARITY_REAUDIT.md #12: "Cloud storage (S3/R2) + signed
URLs" — the local-disk-only gap CLAUDE.md §2/§3's architecture guardrails
call out directly: object storage, not local disk, is where production
drawings belong, and browsers should upload straight to it via presigned
URLs rather than proxying full files through this API server.

Configured entirely via env vars, all optional:
  S3_BUCKET, S3_ENDPOINT_URL (set for R2 / MinIO / any non-default-AWS
  endpoint), S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY, S3_REGION (default
  us-east-1). Unset S3_BUCKET means storage_available() is False and every
  route falls back to the pre-existing local-disk behavior — same
  graceful-degradation rule this backend already applies to every other
  optional dependency (cv2/PIL/fitz/CLIP), except here the *package*
  (boto3) is already a plain requirements.txt dependency per CLAUDE.md §2
  (object storage access isn't "heavy ML"); it's only credentials/bucket
  that are commonly unset in a given environment.

Drawing.file_path doubles as the storage pointer with no schema change: a
local filesystem path (existing behavior, untouched) or an "s3://{key}"
URI (new — bucket is implied by config, not embedded, since a deployment
only ever talks to one configured bucket). Every reader of file_path (AI
inference, tiling, drawing compare) should go through resolve_local_path()
below, which transparently downloads S3-backed files to a temp path for
the duration of the `with` block — so that code never needs to know or
care where the file actually lives.
"""

import contextlib
import os
import tempfile
import uuid
from typing import Optional

S3_URI_PREFIX = "s3://"


def _config() -> Optional[dict]:
    bucket = os.environ.get("S3_BUCKET")
    if not bucket:
        return None
    return {
        "bucket": bucket,
        "endpoint_url": os.environ.get("S3_ENDPOINT_URL") or None,
        "access_key_id": os.environ.get("S3_ACCESS_KEY_ID"),
        "secret_access_key": os.environ.get("S3_SECRET_ACCESS_KEY"),
        "region": os.environ.get("S3_REGION", "us-east-1"),
    }


def storage_available() -> bool:
    try:
        import boto3  # noqa: F401
    except ImportError:
        return False
    return _config() is not None


def _client():
    import boto3
    from botocore.client import Config

    cfg = _config()
    client = boto3.client(
        "s3",
        endpoint_url=cfg["endpoint_url"],
        aws_access_key_id=cfg["access_key_id"],
        aws_secret_access_key=cfg["secret_access_key"],
        region_name=cfg["region"],
        config=Config(signature_version="s3v4"),
    )
    return client, cfg["bucket"]


def make_key(project_id: int, filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    return f"drawings/{project_id}/{uuid.uuid4()}.{ext}"


def to_uri(key: str) -> str:
    return f"{S3_URI_PREFIX}{key}"


def is_storage_uri(file_path: str) -> bool:
    return file_path.startswith(S3_URI_PREFIX)


def key_from_uri(file_path: str) -> str:
    return file_path[len(S3_URI_PREFIX):]


def generate_presigned_upload(key: str, content_type: str, max_bytes: int = 500 * 1024 * 1024, expires_in: int = 900) -> dict:
    """
    Presigned POST — the browser fills in the returned `fields` alongside
    the file and POSTs multipart/form-data straight to `url`; the file
    bytes never touch this API server. Returns {"url", "fields"}.
    """
    client, bucket = _client()
    return client.generate_presigned_post(
        Bucket=bucket, Key=key,
        Fields={"Content-Type": content_type},
        Conditions=[{"Content-Type": content_type}, ["content-length-range", 1, max_bytes]],
        ExpiresIn=expires_in,
    )


def generate_presigned_download(key: str, expires_in: int = 3600) -> str:
    client, bucket = _client()
    return client.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=expires_in)


def upload_bytes(key: str, data: bytes, content_type: Optional[str] = None) -> None:
    client, bucket = _client()
    extra = {"ContentType": content_type} if content_type else {}
    client.put_object(Bucket=bucket, Key=key, Body=data, **extra)


def object_head(key: str) -> Optional[dict]:
    client, bucket = _client()
    try:
        return client.head_object(Bucket=bucket, Key=key)
    except Exception:
        return None


def delete_object(key: str) -> None:
    client, bucket = _client()
    client.delete_object(Bucket=bucket, Key=key)


@contextlib.contextmanager
def resolve_local_path(file_path: str):
    """
    Yields a real local filesystem path for `file_path` — itself if it's
    already local, or an S3 object downloaded to a temp file for the
    duration of the `with` block (cleaned up on exit either way) if it's
    an "s3://" URI. Every consumer of Drawing.file_path (AI inference,
    tiling, drawing compare) should read through this rather than assuming
    a local path.
    """
    if not is_storage_uri(file_path):
        yield file_path
        return

    key = key_from_uri(file_path)
    client, bucket = _client()
    suffix = os.path.splitext(key)[1] or ".bin"
    fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    try:
        client.download_file(bucket, key, tmp_path)
        yield tmp_path
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
