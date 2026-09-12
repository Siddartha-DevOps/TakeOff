import io
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

import storage


class FakeS3Client:
    def __init__(self):
        self.objects = {}
        self.deleted = []
        self.presigned_posts = []
        self.presigned_downloads = []

    def generate_presigned_post(self, **kwargs):
        self.presigned_posts.append(kwargs)
        return {"url": "https://storage.example/upload", "fields": {"key": kwargs["Key"]}}

    def head_bucket(self, Bucket):
        return {"ResponseMetadata": {"HTTPStatusCode": 200}}

    def generate_presigned_url(self, operation, Params, ExpiresIn):
        self.presigned_downloads.append((operation, Params, ExpiresIn))
        return "https://storage.example/private-download?signature=short-lived"

    def put_object(self, Bucket, Key, Body, **kwargs):
        self.objects[Key] = bytes(Body)

    def upload_file(self, filename, bucket, key, ExtraArgs=None):
        self.objects[key] = Path(filename).read_bytes()

    def get_object(self, Bucket, Key, Range=None):
        return {"Body": io.BytesIO(self.objects[Key])}

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "404", "Message": "missing"}}, "HeadObject")
        return {"ContentLength": len(self.objects[Key]), "ContentType": "application/pdf"}

    def download_file(self, bucket, key, filename):
        Path(filename).write_bytes(self.objects[key])

    def delete_object(self, Bucket, Key):
        self.deleted.append(Key)
        self.objects.pop(Key, None)

    def list_objects_v2(self, Bucket, Prefix, ContinuationToken=None):
        return {
            "Contents": [{"Key": key} for key in sorted(self.objects) if key.startswith(Prefix)],
            "IsTruncated": False,
        }

    def delete_objects(self, Bucket, Delete):
        for item in Delete["Objects"]:
            self.deleted.append(item["Key"])
            self.objects.pop(item["Key"], None)
        return {"Deleted": Delete["Objects"]}


@pytest.fixture
def fake_storage(monkeypatch):
    client = FakeS3Client()
    monkeypatch.setattr(storage, "_client", lambda: (client, "takeoff-test"))
    return client


def test_object_keys_are_collision_safe_and_tenant_scoped():
    first = storage.make_key(7, 11, "../../Floor Plan.PDF")
    second = storage.make_key(8, 11, "Floor Plan.PDF")
    repeat = storage.make_key(7, 11, "Floor Plan.PDF")

    assert first.startswith("organizations/7/projects/11/drawings/")
    assert first.endswith(".pdf")
    assert second.startswith("organizations/8/projects/11/drawings/")
    assert first != repeat
    assert storage.key_belongs_to_project(first, 7, 11)
    assert not storage.key_belongs_to_project(first, 8, 11)
    assert "Floor Plan" not in first and ".." not in first


def test_presigned_upload_enforces_type_size_and_expiry(fake_storage):
    result = storage.generate_presigned_upload(
        "organizations/1/projects/2/drawings/file.pdf",
        "application/pdf",
        max_bytes=1234,
        expires_in=321,
    )

    assert result["url"] == "https://storage.example/upload"
    request = fake_storage.presigned_posts[0]
    assert request["Conditions"] == [
        {"Content-Type": "application/pdf"},
        ["content-length-range", 1, 1234],
    ]
    assert request["ExpiresIn"] == 321


def test_presigned_download_is_private_short_lived_and_sanitizes_filename(fake_storage):
    url = storage.generate_presigned_download(
        "organizations/1/projects/2/drawings/file.pdf",
        expires_in=90,
        filename='../../Plan\r\n".pdf',
        content_type="application/pdf",
    )

    assert "signature=" in url
    operation, params, expiry = fake_storage.presigned_downloads[0]
    assert operation == "get_object"
    assert expiry == 90
    assert params["ResponseContentType"] == "application/pdf"
    disposition = params["ResponseContentDisposition"]
    assert "\r" not in disposition and "\n" not in disposition and ".." not in disposition


def test_upload_resolve_after_restart_and_delete_lifecycle(fake_storage, tmp_path):
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.7 durable")
    key = "organizations/1/projects/2/drawings/file.pdf"
    storage.upload_file(key, str(source), "application/pdf")
    uri = storage.to_uri(key)

    # Resolving creates an isolated temporary materialization. No server-local
    # upload path is required, so a fresh backend process can retrieve it.
    with storage.resolve_local_path(uri) as local_path:
        materialized = Path(local_path)
        assert materialized != source
        assert materialized.read_bytes() == source.read_bytes()
        assert materialized.exists()
    assert not materialized.exists()

    assert storage.object_head(key)["ContentLength"] == len(source.read_bytes())
    storage.delete_object(key)
    assert fake_storage.deleted == [key]
    assert storage.object_head(key) is None


def test_generated_artifact_tree_survives_local_cache_loss_and_cleans_up(fake_storage, tmp_path):
    artifact_dir = tmp_path / "tiles"
    (artifact_dir / "3").mkdir(parents=True)
    (artifact_dir / "meta.json").write_text('{"max_level": 3}', encoding="utf-8")
    (artifact_dir / "3" / "0_0.jpg").write_bytes(b"jpeg-tile")
    prefix = storage.drawing_artifact_prefix(7, 11, 19) + "tiles/"

    assert storage.upload_directory(prefix, str(artifact_dir)) == 2
    assert set(fake_storage.objects) == {
        prefix + "meta.json",
        prefix + "3/0_0.jpg",
    }

    restored = tmp_path / "fresh-instance" / "3" / "0_0.jpg"
    storage.download_file(prefix + "3/0_0.jpg", str(restored))
    assert restored.read_bytes() == b"jpeg-tile"
    assert storage.delete_prefix(storage.drawing_artifact_prefix(7, 11, 19)) == 2
    assert fake_storage.objects == {}


def test_local_path_resolution_remains_available_for_development(tmp_path):
    source = tmp_path / "local.png"
    source.write_bytes(b"local-dev-only")
    with storage.resolve_local_path(str(source)) as resolved:
        assert resolved == str(source)
        assert Path(resolved).read_bytes() == b"local-dev-only"


def test_storage_configuration_detects_missing_and_partial_values(monkeypatch):
    monkeypatch.delenv("S3_BUCKET", raising=False)
    assert "S3_BUCKET" in storage.storage_configuration_errors()
    assert storage.storage_available() is False

    monkeypatch.setenv("S3_BUCKET", "takeoff")
    monkeypatch.setenv("S3_ENDPOINT_URL", "https://r2.example")
    monkeypatch.setenv("S3_ACCESS_KEY_ID", "access")
    monkeypatch.delenv("S3_SECRET_ACCESS_KEY", raising=False)
    errors = storage.storage_configuration_errors()
    assert any("set together" in error for error in errors)
    assert storage.storage_available() is False


def test_readiness_checks_the_configured_bucket(fake_storage, monkeypatch):
    monkeypatch.setattr(storage, "storage_available", lambda: True)
    assert storage.storage_ready() is True


def test_readiness_fails_closed_when_bucket_is_unreachable(monkeypatch):
    class UnreachableClient:
        def head_bucket(self, Bucket):
            raise RuntimeError("provider unavailable")

    monkeypatch.setattr(storage, "storage_available", lambda: True)
    monkeypatch.setattr(storage, "_client", lambda: (UnreachableClient(), "takeoff-test"))
    assert storage.storage_ready() is False


def test_head_distinguishes_missing_objects_from_provider_failure(monkeypatch):
    class BrokenClient:
        def head_object(self, **kwargs):
            raise ClientError({"Error": {"Code": "AccessDenied", "Message": "denied"}}, "HeadObject")

    monkeypatch.setattr(storage, "_client", lambda: (BrokenClient(), "takeoff-test"))
    with pytest.raises(storage.StorageOperationError, match="Could not inspect"):
        storage.object_head("organizations/1/projects/2/drawings/file.pdf")


def test_required_storage_client_fails_with_actionable_configuration_error(monkeypatch):
    monkeypatch.delenv("S3_BUCKET", raising=False)
    with pytest.raises(storage.StorageConfigurationError, match="S3_BUCKET"):
        storage._client()
