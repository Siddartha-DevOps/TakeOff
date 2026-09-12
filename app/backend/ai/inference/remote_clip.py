"""Client for the private Hugging Face Space CLIP endpoints.

The Render API intentionally does not install torch or model weights.  It sends
text and drawing regions to the existing private ZeroGPU Space and only stores
the returned, normalized 512-dimensional vectors in pgvector.
"""

from __future__ import annotations

import os
from functools import lru_cache


class RemoteClipError(RuntimeError):
    pass


def remote_clip_configured() -> bool:
    return bool(os.environ.get("AI_INFERENCE_SPACE_ID") and os.environ.get("HF_TOKEN"))


class RemoteClipEmbeddings:
    def __init__(
        self,
        *,
        space_id: str | None = None,
        token: str | None = None,
        timeout_seconds: float | None = None,
    ):
        self.space_id = space_id or os.environ.get("AI_INFERENCE_SPACE_ID", "")
        self.token = token or os.environ.get("HF_TOKEN", "")
        self.timeout_seconds = max(
            1.0,
            float(timeout_seconds or os.environ.get("AI_SEARCH_TIMEOUT_SECONDS", "60")),
        )
        if not self.space_id or not self.token:
            raise RemoteClipError("AI_INFERENCE_SPACE_ID and HF_TOKEN are required for production AI Search")

    @lru_cache(maxsize=1)
    def _client(self):
        try:
            from gradio_client import Client
            return Client(self.space_id, token=self.token, verbose=False)
        except Exception as exc:
            raise RemoteClipError(f"Could not connect to the private CLIP service: {exc}") from exc

    def _predict(self, *args, api_name: str):
        job = None
        try:
            job = self._client().submit(*args, api_name=api_name)
            return job.result(timeout=self.timeout_seconds)
        except TimeoutError as exc:
            if job is not None:
                try:
                    job.cancel()
                except Exception:
                    pass
            raise RemoteClipError("CLIP service timed out; retry after the GPU queue clears") from exc

    @staticmethod
    def _validate_vector(value) -> list[float]:
        if not isinstance(value, list) or len(value) != 512:
            raise RemoteClipError("CLIP service returned an invalid embedding")
        return [float(item) for item in value]

    def embed_text(self, text: str) -> list[float]:
        try:
            result = self._predict(text, api_name="/embed_clip_text")
        except Exception as exc:
            raise RemoteClipError(f"CLIP text embedding failed: {exc}") from exc
        payload = result if isinstance(result, dict) else {}
        return self._validate_vector(payload.get("embedding"))

    def embed_regions(self, image_path: str, regions: list[dict]) -> list[dict]:
        try:
            from gradio_client import handle_file
            result = self._predict(
                handle_file(image_path), regions, api_name="/embed_clip_regions"
            )
        except Exception as exc:
            raise RemoteClipError(f"CLIP region embedding failed: {exc}") from exc
        payload = result if isinstance(result, dict) else {}
        encoded = payload.get("regions")
        if not isinstance(encoded, list) or len(encoded) != len(regions):
            raise RemoteClipError("CLIP service returned an invalid region batch")
        return [
            {**item, "embedding": self._validate_vector(item.get("embedding"))}
            for item in encoded
        ]


@lru_cache(maxsize=1)
def get_remote_clip() -> RemoteClipEmbeddings:
    return RemoteClipEmbeddings()
