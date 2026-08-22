"""Private Hugging Face Space adapter for the lightweight Render API.

The base API image intentionally excludes torch and ultralytics.  This module
preserves the local inference engine's ``analyze`` contract while sending the
heavy prediction to the private ZeroGPU Gradio Space.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Callable

from .engine import TakeoffAnalysis, partition_detections, raster_quantities

DEFAULT_API_NAME = "/predict_spaces"
DEFAULT_TIMEOUT_SECONDS = 90.0


class RemoteInferenceError(RuntimeError):
    """Raised when the configured remote inference service cannot respond."""


def _required(value: str | None, name: str) -> str:
    clean = (value or "").strip()
    if not clean:
        raise RemoteInferenceError(f"{name} is required for remote AI inference")
    return clean


def _client_error_message(error: Exception) -> str:
    """Return an actionable message without leaking credentials or internals."""
    message = str(error).lower()
    if "no gpu was available" in message or "queue" in message:
        return "The shared AI GPU is busy. Please retry the analysis later."
    if "401" in message or "403" in message or "unauthorized" in message:
        return "The private AI service rejected its credentials."
    return "The remote AI service could not complete the analysis."


def _payload_to_detections(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Translate the Space's stable transport schema to the engine schema."""
    width = int(payload.get("image_width") or 0)
    height = int(payload.get("image_height") or 0)
    raw_detections = payload.get("detections")
    if width <= 0 or height <= 0 or not isinstance(raw_detections, list):
        raise RemoteInferenceError(
            "The remote AI service returned an invalid response."
        )

    detections: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_detections):
        if not isinstance(raw, dict):
            raise RemoteInferenceError(
                "The remote AI service returned an invalid response."
            )
        bbox = raw.get("bbox_xyxy")
        if not isinstance(bbox, list) or len(bbox) != 4:
            raise RemoteInferenceError(
                "The remote AI service returned an invalid response."
            )
        try:
            box = [float(value) for value in bbox]
            confidence = float(raw.get("confidence", 0.0))
        except (TypeError, ValueError) as error:
            raise RemoteInferenceError(
                "The remote AI service returned an invalid response."
            ) from error

        label = str(raw.get("class_name") or "unknown")
        detection: dict[str, Any] = {
            "id": f"{label[:1] or 'd'}{index}",
            "label": label,
            "bbox": [round(value, 1) for value in box],
            "confidence": round(confidence, 3),
            "area": round(max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1]), 1),
        }

        normalized = raw.get("polygon_normalized") or []
        if isinstance(normalized, list):
            polygon = []
            for point in normalized:
                if not isinstance(point, (list, tuple)) or len(point) != 2:
                    continue
                try:
                    polygon.append(
                        [
                            round(float(point[0]) * width, 2),
                            round(float(point[1]) * height, 2),
                        ]
                    )
                except (TypeError, ValueError):
                    continue
            if polygon:
                detection["polygon"] = polygon
        detections.append(detection)
    return detections


class RemoteSpaceInference:
    """Drop-in ``TakeoffAIInference`` replacement backed by a private Space."""

    backend = "huggingface_space"
    device = "remote:zero-gpu"
    model = None

    def __init__(
        self,
        space_id: str,
        token: str,
        *,
        api_name: str = DEFAULT_API_NAME,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        client_factory: Callable[[], Any] | None = None,
        file_handler: Callable[[str], Any] | None = None,
    ) -> None:
        self.space_id = _required(space_id, "AI_INFERENCE_SPACE_ID")
        self._token = _required(token, "HF_TOKEN")
        self.api_name = api_name if api_name.startswith("/") else f"/{api_name}"
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self._client_factory = client_factory
        self._file_handler = file_handler
        self._client = None

    @classmethod
    def from_env(cls) -> "RemoteSpaceInference":
        return cls(
            os.environ.get("AI_INFERENCE_SPACE_ID", ""),
            os.environ.get("HF_TOKEN", ""),
            api_name=os.environ.get("AI_INFERENCE_API_NAME", DEFAULT_API_NAME),
            timeout_seconds=float(
                os.environ.get("AI_INFERENCE_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)
            ),
        )

    @property
    def available(self) -> bool:
        return True

    def _get_client(self):
        if self._client is None:
            if self._client_factory is not None:
                self._client = self._client_factory()
            else:
                from gradio_client import Client

                self._client = Client(
                    self.space_id,
                    token=self._token,
                    verbose=False,
                    download_files=False,
                    analytics_enabled=False,
                )
        return self._client

    def _file_input(self, image_path: str):
        if self._file_handler is not None:
            return self._file_handler(image_path)
        from gradio_client import handle_file

        return handle_file(image_path)

    def analyze(
        self,
        image_path: str,
        drawing_id: int = 0,
        conf: float = 0.35,
        iou: float = 0.45,
        **_: Any,
    ) -> TakeoffAnalysis:
        path = Path(image_path)
        if not path.is_file():
            raise RemoteInferenceError("The drawing image is unavailable for analysis.")

        started = time.monotonic()
        job = None
        try:
            job = self._get_client().submit(
                self._file_input(str(path)),
                float(conf),
                float(iou),
                api_name=self.api_name,
            )
            result = job.result(timeout=self.timeout_seconds)
        except TimeoutError as error:
            if job is not None:
                try:
                    job.cancel()
                except Exception:
                    pass
            raise RemoteInferenceError(
                "The remote AI service timed out. Please retry the analysis later."
            ) from error
        except RemoteInferenceError:
            raise
        except Exception as error:
            raise RemoteInferenceError(_client_error_message(error)) from error

        if not isinstance(result, (tuple, list)) or len(result) != 2:
            raise RemoteInferenceError(
                "The remote AI service returned an invalid response."
            )
        payload = result[1]
        if not isinstance(payload, dict) or payload.get("status") != "ok":
            raise RemoteInferenceError(
                "The remote AI service returned an invalid response."
            )

        detections = _payload_to_detections(payload)
        rooms, doors, windows, walls, balconies, summary, average = (
            partition_detections(detections)
        )
        return TakeoffAnalysis(
            drawing_id=drawing_id,
            processing_time_ms=int((time.monotonic() - started) * 1000),
            ai_model_version=str(payload.get("model_version") or "remote-space"),
            rooms=rooms,
            doors=doors,
            windows=windows,
            walls=walls,
            balconies=balconies,
            summary=summary,
            quantities=raster_quantities(rooms, doors, windows, walls),
            confidence_avg=average,
            model_available=True,
            status="ok",
            device=self.device,
        )
