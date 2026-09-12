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
  us-east-1). Unset S3_BUCKET means storage_available() is False. Development
  may use the local-disk fallback, but production/staging (or an explicit
  REQUIRE_OBJECT_STORAGE=true) rejects uploads rather than acknowledge files
  that will disappear from an ephemeral instance. The *package*
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
import mimetypes
import os
from pathlib import Path
import re
import tempfile
import uuid
from typing import Optional

S3_URI_PREFIX = "s3://"


class StorageConfigurationError(RuntimeError):
    """The deployment requested object storage but its configuration is incomplete."""


class StorageOperationError(RuntimeError):
    """The configured object store could not complete an operation."""


def _config() -> Optional[dict]:
    bucket = (os.environ.get("S3_BUCKET") or "").strip()
    if not bucket:
        return None
    return {
        "bucket": bucket,
        "endpoint_url": (os.environ.get("S3_ENDPOINT_URL") or "").strip() or None,
        "access_key_id": (os.environ.get("S3_ACCESS_KEY_ID") or "").strip() or None,
        "secret_access_key": (os.environ.get("S3_SECRET_ACCESS_KEY") or "").strip() or None,
        "region": (os.environ.get("S3_REGION") or "us-east-1").strip(),
    }


def storage_configuration_errors() -> list[str]:
    """Return actionable, non-secret configuration errors."""
    cfg = _config()
    if cfg is None:
        return ["S3_BUCKET"]
    errors = []
    if not cfg["region"]:
        errors.append("S3_REGION")
    access_key = cfg["access_key_id"]
    secret_key = cfg["secret_access_key"]
    if bool(access_key) != bool(secret_key):
        errors.append("S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY must be set together")
    if cfg["endpoint_url"] and not (access_key and secret_key):
        errors.append("S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY (required for S3_ENDPOINT_URL)")
    try:
        import boto3  # noqa: F401
    except ImportError:
        errors.append("boto3 package")
    return errors


def storage_available() -> bool:
    return not storage_configuration_errors()


def storage_ready() -> bool:
    """Readiness probe: configuration is complete and the bucket is reachable."""
    if not storage_available():
        return False
    try:
        client, bucket = _client()
        client.head_bucket(Bucket=bucket)
        return True
    except Exception:
        return False


def object_storage_required() -> bool:
    """Default to durable uploads in production, with an explicit override."""
    configured = os.environ.get("REQUIRE_OBJECT_STORAGE")
    if configured is not None:
        return configured.strip().lower() in {"1", "true", "yes", "on"}
    return os.environ.get("ENVIRONMENT", "development").strip().lower() in {"production", "prod", "staging"}


def _client():
    import boto3
    from botocore.client import Config

    cfg = _config()
    errors = storage_configuration_errors()
    if errors or cfg is None:
        raise StorageConfigurationError(
            "Object storage is not configured: " + ", ".join(errors or ["S3_BUCKET"])
        )
    client = boto3.client(
        "s3",
        endpoint_url=cfg["endpoint_url"],
        aws_access_key_id=cfg["access_key_id"],
        aws_secret_access_key=cfg["secret_access_key"],
        region_name=cfg["region"],
        config=Config(signature_version="s3v4"),
    )
    return client, cfg["bucket"]


def project_key_prefix(organization_id: int, project_id: int) -> str:
    return f"organizations/{int(organization_id)}/projects/{int(project_id)}/drawings/"


def make_key(organization_id: int, project_id: int, filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    return f"{project_key_prefix(organization_id, project_id)}{uuid.uuid4()}.{ext}"


def key_belongs_to_project(key: str, organization_id: int, project_id: int) -> bool:
    return key.startswith(project_key_prefix(organization_id, project_id))


def drawing_artifact_prefix(organization_id: int, project_id: int, drawing_id: int) -> str:
    return (
        f"organizations/{int(organization_id)}/projects/{int(project_id)}/"
        f"artifacts/drawings/{int(drawing_id)}/"
    )


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
    try:
        return client.generate_presigned_post(
            Bucket=bucket, Key=key,
            Fields={"Content-Type": content_type},
            Conditions=[{"Content-Type": content_type}, ["content-length-range", 1, max_bytes]],
            ExpiresIn=expires_in,
        )
    except Exception as exc:
        raise StorageOperationError("Could not create a signed upload") from exc


def _safe_download_filename(filename: str) -> str:
    name = os.path.basename(filename or "drawing")
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)[:180] or "drawing"


def generate_presigned_download(
    key: str,
    expires_in: int = 3600,
    *,
    filename: Optional[str] = None,
    content_type: Optional[str] = None,
) -> str:
    client, bucket = _client()
    params = {"Bucket": bucket, "Key": key}
    if filename:
        params["ResponseContentDisposition"] = f'attachment; filename="{_safe_download_filename(filename)}"'
    if content_type:
        params["ResponseContentType"] = content_type
    try:
        return client.generate_presigned_url("get_object", Params=params, ExpiresIn=expires_in)
    except Exception as exc:
        raise StorageOperationError("Could not create a signed download") from exc


def upload_bytes(key: str, data: bytes, content_type: Optional[str] = None) -> None:
    client, bucket = _client()
    extra = {"ContentType": content_type} if content_type else {}
    try:
        client.put_object(Bucket=bucket, Key=key, Body=data, **extra)
    except Exception as exc:
        raise StorageOperationError(f"Could not upload object {key!r}") from exc


def upload_file(key: str, file_path: str, content_type: Optional[str] = None) -> None:
    client, bucket = _client()
    extra = {"ContentType": content_type} if content_type else None
    try:
        client.upload_file(file_path, bucket, key, ExtraArgs=extra or {})
    except Exception as exc:
        raise StorageOperationError(f"Could not upload object {key!r}") from exc


def download_file(key: str, destination: str) -> None:
    client, bucket = _client()
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        client.download_file(bucket, key, str(target))
    except Exception as exc:
        target.unlink(missing_ok=True)
        raise StorageOperationError(f"Could not download object {key!r}") from exc


def upload_directory(prefix: str, directory: str) -> int:
    """Persist a generated artifact tree under one tenant-scoped prefix."""
    root = Path(directory)
    uploaded = 0
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        upload_file(f"{prefix.rstrip('/')}/{relative}", str(path), content_type)
        uploaded += 1
    return uploaded


def delete_prefix(prefix: str) -> int:
    """Delete every generated artifact under a known tenant/project prefix."""
    client, bucket = _client()
    deleted = 0
    continuation = None
    try:
        while True:
            params = {"Bucket": bucket, "Prefix": prefix}
            if continuation:
                params["ContinuationToken"] = continuation
            response = client.list_objects_v2(**params)
            objects = [{"Key": item["Key"]} for item in response.get("Contents", [])]
            if objects:
                client.delete_objects(Bucket=bucket, Delete={"Objects": objects, "Quiet": True})
                deleted += len(objects)
            if not response.get("IsTruncated"):
                break
            continuation = response.get("NextContinuationToken")
        return deleted
    except Exception as exc:
        raise StorageOperationError(f"Could not delete object prefix {prefix!r}") from exc


def read_prefix(key: str, size: int = 16) -> bytes:
    client, bucket = _client()
    try:
        response = client.get_object(Bucket=bucket, Key=key, Range=f"bytes=0-{size - 1}")
        return response["Body"].read(size)
    except Exception as exc:
        raise StorageOperationError(f"Could not read object {key!r}") from exc


def object_head(key: str) -> Optional[dict]:
    client, bucket = _client()
    try:
        return client.head_object(Bucket=bucket, Key=key)
    except Exception as exc:
        try:
            from botocore.exceptions import ClientError
            if isinstance(exc, ClientError):
                error = exc.response.get("Error", {})
                if str(error.get("Code", "")) in {"404", "NoSuchKey", "NotFound"}:
                    return None
        except ImportError:
            pass
        raise StorageOperationError(f"Could not inspect object {key!r}") from exc


def delete_object(key: str) -> None:
    client, bucket = _client()
    try:
        client.delete_object(Bucket=bucket, Key=key)
    except Exception as exc:
        raise StorageOperationError(f"Could not delete object {key!r}") from exc


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
        try:
            client.download_file(bucket, key, tmp_path)
        except Exception as exc:
            raise StorageOperationError(f"Could not download object {key!r}") from exc
        yield tmp_path
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
