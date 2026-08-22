"""TakeOff.ai private ZeroGPU Gradio inference service."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import gradio as gr
import spaces
from huggingface_hub import hf_hub_download
from PIL import Image
from ultralytics import YOLO

from result_schema import serialize_result


MODEL_REPO = "Siddartha96/takeoff-spaces-yolov8m-seg"
MODEL_FILE = "best.pt"
MODEL_SHA256 = "2cc2cfffaa294f9915a2fddab9812f06b10450e8149e75d5d3361f5b792c9acd"
MODEL_VERSION = "resplan-yolov8m-seg-12ep-640-v1"


def _sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


token = os.environ.get("HF_TOKEN")
if not token:
    raise RuntimeError("HF_TOKEN Space secret is required to read the private model")

model_path = hf_hub_download(
    repo_id=MODEL_REPO,
    filename=MODEL_FILE,
    repo_type="model",
    token=token,
)
actual_sha256 = _sha256(model_path)
if actual_sha256 != MODEL_SHA256:
    raise RuntimeError(
        f"model checksum mismatch: expected {MODEL_SHA256}, found {actual_sha256}"
    )

# ZeroGPU provides CUDA emulation during module initialization. Placing the
# model on CUDA here lets the decorator attach real GPU capacity per request.
model = YOLO(model_path)
model.to("cuda")


@spaces.GPU(duration=45)
def predict_spaces(image_path: str, confidence: float, iou: float):
    if not image_path:
        raise gr.Error("Upload a floor-plan image first")
    results = model.predict(
        source=image_path,
        conf=float(confidence),
        iou=float(iou),
        imgsz=640,
        max_det=300,
        device=0,
        verbose=False,
    )
    result = results[0]
    payload = serialize_result(result)
    payload.update({
        "status": "ok",
        "model_version": MODEL_VERSION,
        "model_sha256": MODEL_SHA256,
    })
    # Ultralytics plots BGR arrays; Gradio/Pillow expect RGB.
    annotated = Image.fromarray(result.plot()[..., ::-1].copy())
    return annotated, payload


with gr.Blocks(title="TakeOff.ai Spaces Inference") as demo:
    gr.Markdown(
        "# TakeOff.ai — Room Segmentation\n"
        "Private ZeroGPU inference for ResPlan-pretrained floor-plan spaces."
    )
    with gr.Row():
        image = gr.Image(type="filepath", label="Floor-plan image")
        annotated = gr.Image(type="pil", label="Detected spaces")
    with gr.Row():
        confidence = gr.Slider(0.05, 0.95, value=0.35, step=0.05, label="Confidence")
        iou = gr.Slider(0.1, 0.9, value=0.45, step=0.05, label="IoU")
    run = gr.Button("Detect spaces", variant="primary")
    detections = gr.JSON(label="Detection JSON")
    run.click(
        fn=predict_spaces,
        inputs=[image, confidence, iou],
        outputs=[annotated, detections],
        api_name="predict_spaces",
        api_visibility="public",
        concurrency_limit=1,
    )

demo.queue(default_concurrency_limit=1).launch()
