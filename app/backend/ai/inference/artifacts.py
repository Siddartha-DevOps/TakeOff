"""Secure provisioning for private model artifacts.

Weights stay out of git. GPU deployments may pull the pinned ACTIVE model from
Hugging Face into the runtime volume before ``InferenceEngine`` is created.
Downloads are checksum-verified and atomically installed, so a partial or
tampered file is never exposed at the stable model path.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path
from typing import Callable, Optional


class ModelProvisionError(RuntimeError):
    """Raised when a configured model cannot be installed safely."""


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _expected_digest(value: str) -> str:
    digest = (value or "").strip().lower()
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ModelProvisionError("AI_MODEL_SHA256 must be a 64-character SHA-256 digest")
    return digest


def provision_hf_model(
    target: str | Path,
    *,
    repo_id: str,
    filename: str,
    expected_sha256: str,
    token: Optional[str] = None,
    downloader: Optional[Callable[..., str]] = None,
) -> Path:
    """Ensure ``target`` contains the exact pinned private Hub artifact.

    An already-correct target is reused without requiring network access or a
    token. Otherwise the file is downloaded, verified in a temporary file in
    the destination directory, and atomically moved into place.
    """
    destination = Path(target)
    expected = _expected_digest(expected_sha256)
    if destination.is_file() and file_sha256(destination) == expected:
        return destination

    if not repo_id.strip() or not filename.strip():
        raise ModelProvisionError("AI_MODEL_REPO_ID and AI_MODEL_FILENAME are required")
    if not token:
        raise ModelProvisionError("HF_TOKEN is required to download the private model")

    if downloader is None:
        try:
            from huggingface_hub import hf_hub_download
        except ImportError as exc:
            raise ModelProvisionError(
                "huggingface_hub is required for AI model provisioning"
            ) from exc
        downloader = hf_hub_download

    downloaded = Path(downloader(
        repo_id=repo_id,
        filename=filename,
        repo_type="model",
        token=token,
    ))
    if not downloaded.is_file():
        raise ModelProvisionError(f"model download did not produce a file: {downloaded}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent, delete=False
        ) as temp_handle:
            temp_path = Path(temp_handle.name)
            with downloaded.open("rb") as source:
                shutil.copyfileobj(source, temp_handle, length=1024 * 1024)
        actual = file_sha256(temp_path)
        if actual != expected:
            raise ModelProvisionError(
                f"model checksum mismatch: expected {expected}, found {actual}"
            )
        os.replace(temp_path, destination)
        temp_path = None
        return destination
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
