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
from transformers import CLIPModel, CLIPProcessor
import torch

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

CLIP_MODEL_ID = "openai/clip-vit-base-patch32"
clip_model = CLIPModel.from_pretrained(CLIP_MODEL_ID)
clip_processor = CLIPProcessor.from_pretrained(CLIP_MODEL_ID)


def _normalized(values):
    values = values / values.norm(dim=-1, keepdim=True)
    return values[0].detach().cpu().tolist()


@spaces.GPU(duration=20)
def embed_clip_text(text: str):
    text = (text or "").strip()
    if not text:
        raise gr.Error("Enter search text")
    clip_model.to("cuda")
    inputs = clip_processor(text=[text], return_tensors="pt", padding=True).to("cuda")
    with torch.inference_mode():
        vector = _normalized(clip_model.get_text_features(**inputs))
    return {"status": "ok", "model": CLIP_MODEL_ID, "embedding": vector}


@spaces.GPU(duration=30)
def embed_clip_regions(image_path: str, regions: list[dict]):
    if not image_path:
        raise gr.Error("Upload a drawing image")
    if not isinstance(regions, list) or not regions or len(regions) > 500:
        raise gr.Error("Provide between 1 and 500 regions")
    source = Image.open(image_path).convert("RGB")
    crops = []
    valid = []
    for region in regions:
        bbox = region.get("bbox") if isinstance(region, dict) else None
        if not isinstance(bbox, list) or len(bbox) != 4:
            raise gr.Error("Every region needs bbox [x1,y1,x2,y2]")
        x1, y1, x2, y2 = [int(float(value)) for value in bbox]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(source.width, x2), min(source.height, y2)
        if x2 <= x1 or y2 <= y1:
            raise gr.Error("A region is empty or outside the drawing")
        crops.append(source.crop((x1, y1, x2, y2)))
        valid.append({key: value for key, value in region.items() if key != "embedding"})
    clip_model.to("cuda")
    inputs = clip_processor(images=crops, return_tensors="pt", padding=True).to("cuda")
    with torch.inference_mode():
        vectors = clip_model.get_image_features(**inputs)
        vectors = vectors / vectors.norm(dim=-1, keepdim=True)
    return {
        "status": "ok",
        "model": CLIP_MODEL_ID,
        "regions": [
            {**region, "embedding": vector.detach().cpu().tolist()}
            for region, vector in zip(valid, vectors)
        ],
    }


@spaces.GPU(duration=15)
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
    # Named API endpoints used by the Render backend.  They share the same
    # private Space and ZeroGPU queue as room detection, so no second paid GPU
    # service is required.
    clip_text = gr.Textbox(visible=False)
    clip_text_json = gr.JSON(visible=False)
    clip_text.submit(
        fn=embed_clip_text, inputs=[clip_text], outputs=[clip_text_json],
        api_name="embed_clip_text", api_visibility="public", concurrency_limit=1,
    )
    clip_image = gr.Image(type="filepath", visible=False)
    clip_regions = gr.JSON(visible=False)
    clip_regions_json = gr.JSON(visible=False)
    clip_regions.change(
        fn=embed_clip_regions, inputs=[clip_image, clip_regions], outputs=[clip_regions_json],
        api_name="embed_clip_regions", api_visibility="public", concurrency_limit=1,
    )

demo.queue(default_concurrency_limit=1).launch()
