from pathlib import Path

import pytest

from ai.inference.artifacts import ModelProvisionError, file_sha256, provision_hf_model


def test_reuses_verified_local_model_without_token_or_download(tmp_path):
    target = tmp_path / "best.pt"
    target.write_bytes(b"verified weights")
    expected = file_sha256(target)

    def must_not_download(**_kwargs):
        raise AssertionError("download should not run")

    assert provision_hf_model(
        target,
        repo_id="private/model",
        filename="best.pt",
        expected_sha256=expected,
        downloader=must_not_download,
    ) == target


def test_downloads_verifies_and_atomically_installs(tmp_path):
    source = tmp_path / "hub-cache.pt"
    source.write_bytes(b"new trained weights")
    target = tmp_path / "models" / "best.pt"

    def download(**kwargs):
        assert kwargs == {
            "repo_id": "owner/model",
            "filename": "best.pt",
            "repo_type": "model",
            "token": "secret",
        }
        return str(source)

    result = provision_hf_model(
        target,
        repo_id="owner/model",
        filename="best.pt",
        expected_sha256=file_sha256(source),
        token="secret",
        downloader=download,
    )

    assert result == target
    assert target.read_bytes() == b"new trained weights"
    assert not list(target.parent.glob("*.tmp"))


def test_rejects_bad_checksum_without_replacing_existing_target(tmp_path):
    source = tmp_path / "download.pt"
    source.write_bytes(b"tampered")
    target = tmp_path / "best.pt"
    target.write_bytes(b"old weights")

    with pytest.raises(ModelProvisionError, match="checksum mismatch"):
        provision_hf_model(
            target,
            repo_id="owner/model",
            filename="best.pt",
            expected_sha256="0" * 64,
            token="secret",
            downloader=lambda **_kwargs: str(source),
        )

    assert target.read_bytes() == b"old weights"


@pytest.mark.parametrize("digest", ["", "abc", "z" * 64])
def test_requires_valid_sha256(digest):
    with pytest.raises(ModelProvisionError, match="SHA-256"):
        provision_hf_model(
            Path("unused.pt"),
            repo_id="owner/model",
            filename="best.pt",
            expected_sha256=digest,
        )
