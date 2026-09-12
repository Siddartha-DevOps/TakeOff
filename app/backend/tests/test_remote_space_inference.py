from __future__ import annotations

from pathlib import Path
import sys
import types

import pytest

from ai.inference.remote_space import RemoteInferenceError, RemoteSpaceInference


class FakeJob:
    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error
        self.timeout = None
        self.cancelled = False

    def result(self, timeout=None):
        self.timeout = timeout
        if self._error:
            raise self._error
        return self._result

    def cancel(self):
        self.cancelled = True


class FakeClient:
    def __init__(self, job):
        self.job = job
        self.call = None

    def submit(self, *args, **kwargs):
        self.call = (args, kwargs)
        return self.job


def _engine(tmp_path: Path, job: FakeJob):
    image = tmp_path / "plan.png"
    image.write_bytes(b"image")
    client = FakeClient(job)
    engine = RemoteSpaceInference(
        "owner/private-space",
        "hf_secret",
        timeout_seconds=12,
        client_factory=lambda: client,
        file_handler=lambda path: {"path": path},
    )
    return engine, client, image


def test_remote_space_maps_transport_payload_to_takeoff_analysis(tmp_path):
    payload = {
        "status": "ok",
        "model_version": "resplan-v1",
        "image_width": 1000,
        "image_height": 500,
        "detections": [
            {
                "class_name": "bedroom",
                "confidence": 0.91,
                "bbox_xyxy": [100, 50, 400, 250],
                "polygon_normalized": [[0.1, 0.1], [0.4, 0.5]],
            },
            {
                "class_name": "balcony",
                "confidence": 0.7,
                "bbox_xyxy": [500, 50, 700, 200],
                "polygon_normalized": [],
            },
        ],
    }
    job = FakeJob(result=("annotated.png", payload))
    engine, client, image = _engine(tmp_path, job)

    analysis = engine.analyze(str(image), drawing_id=42)

    assert analysis.drawing_id == 42
    assert analysis.ai_model_version == "resplan-v1"
    assert analysis.device == "remote:zero-gpu"
    assert analysis.summary["rooms"] == 1
    assert analysis.rooms[0]["polygon"] == [[100.0, 50.0], [400.0, 250.0]]
    assert len(analysis.balconies) == 1
    assert client.call[1]["api_name"] == "/predict_spaces"
    assert job.timeout == 12


def test_remote_space_turns_queue_failure_into_actionable_error(tmp_path):
    job = FakeJob(error=RuntimeError("No GPU was available after 60s"))
    engine, _, image = _engine(tmp_path, job)

    with pytest.raises(RemoteInferenceError, match="shared AI GPU is busy") as raised:
        engine.analyze(str(image))

    assert "hf_secret" not in str(raised.value)


def test_remote_space_rejects_malformed_payload(tmp_path):
    job = FakeJob(result=("annotated.png", {"status": "ok", "detections": []}))
    engine, _, image = _engine(tmp_path, job)

    with pytest.raises(RemoteInferenceError, match="invalid response"):
        engine.analyze(str(image))


def test_remote_space_cancels_timed_out_job(tmp_path):
    job = FakeJob(error=TimeoutError())
    engine, _, image = _engine(tmp_path, job)

    with pytest.raises(RemoteInferenceError, match="timed out"):
        engine.analyze(str(image))

    assert job.cancelled is True


def test_remote_space_requires_private_service_configuration():
    with pytest.raises(RemoteInferenceError, match="AI_INFERENCE_SPACE_ID"):
        RemoteSpaceInference("", "hf_secret")
    with pytest.raises(RemoteInferenceError, match="HF_TOKEN"):
        RemoteSpaceInference("owner/private-space", "")


def test_remote_space_passes_private_token_to_current_client_api(monkeypatch):
    captured = {}

    class Client:
        def __init__(self, src, *, token, verbose, download_files, analytics_enabled):
            captured.update(
                src=src,
                token=token,
                verbose=verbose,
                download_files=download_files,
                analytics_enabled=analytics_enabled,
            )

    monkeypatch.setitem(
        sys.modules, "gradio_client", types.SimpleNamespace(Client=Client)
    )
    engine = RemoteSpaceInference("owner/private-space", "hf_secret")

    engine._get_client()

    assert captured == {
        "src": "owner/private-space",
        "token": "hf_secret",
        "verbose": False,
        "download_files": False,
        "analytics_enabled": False,
    }
