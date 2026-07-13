"""
TakeOff.ai — Modal inference endpoint (Phase 0 infra scaffolding).

Implements CLAUDE.md §7's stated GPU-service contract literally:
    POST /infer { sheetUrl, task } -> { detections: [...], status }

and CLAUDE.md §2 guardrail #1/#2: inference never runs inside a Vercel
route — this is the separate GPU service a Vercel/Next.js route (or, in
this repo's current FastAPI backend, routes/takeoff_routes.py) calls
asynchronously instead.

This module only defines the endpoint; deploying it does not put it in
the request path of anything yet — app/backend/ai/detection_engine.py
remains the live inference path used by _run_ai_analysis. Wiring this in
as an alternative/replacement backend is a separate, later change, not
part of Phase 0 infra setup.

Detection dict shape (bbox/confidence/class fields) intentionally mirrors
app/backend/ai/detection_engine.py's existing output so a future caller
can consume either source without a translation layer.

Deploy (does not serve traffic until deployed, and requires
`modal token set` to have been run first — see infra/modal_gpu.py's
docstring for the setup commands):
    modal deploy infra/modal_inference.py
"""

from pathlib import Path

import modal

APP_NAME = "takeoff-ai-inference"
REPO_ROOT = Path(__file__).resolve().parent.parent
DATASETS_SRC = REPO_ROOT / "datasets"

app = modal.App(APP_NAME)

inference_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("libgl1", "libglib2.0-0")
    .pip_install(
        "ultralytics>=8.1.0",
        "torch",
        "torchvision",
        "fastapi[standard]",
        "requests",
        "pyyaml",
    )
    .add_local_dir(str(DATASETS_SRC), remote_path="/root/datasets")
)

models_volume = modal.Volume.from_name("takeoff-ai-models", create_if_missing=True)

ROOM_MODEL_PATH = "/models/rooms_v1.pt"
SYMBOL_MODEL_PATH = "/models/symbol_counts/yolov8-seg.pt"  # matches infra/modal_gpu.py::train_symbols()'s output_dir, and ai/detect_symbols.py's own DEFAULT_OUTPUT convention

# Containers stay warm for 5 minutes after the last request so consecutive
# sheet uploads in one takeoff session don't each pay a cold-start model load.
CONTAINER_IDLE_TIMEOUT = 300


@app.cls(
    image=inference_image,
    gpu="A10G",
    volumes={"/models": models_volume},
    scaledown_window=CONTAINER_IDLE_TIMEOUT,
)
class InferenceService:
    @modal.enter()
    def load_models(self):
        from ultralytics import YOLO

        self.rooms_model = YOLO(ROOM_MODEL_PATH) if Path(ROOM_MODEL_PATH).exists() else None
        self.symbols_model = YOLO(SYMBOL_MODEL_PATH) if Path(SYMBOL_MODEL_PATH).exists() else None

    @modal.method()
    def infer(self, image_bytes: bytes, task: str) -> list:
        import io

        import numpy as np
        from PIL import Image

        model = self.rooms_model if task == "rooms" else self.symbols_model
        if model is None:
            raise RuntimeError(f"No trained weights available for task={task!r} — has infra/modal_gpu.py's train_{task}() run yet?")

        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        results = model.predict(np.array(image), verbose=False)[0]

        detections = []
        names = results.names
        boxes = results.boxes
        masks = getattr(results, "masks", None)
        for i in range(len(boxes)):
            x1, y1, x2, y2 = [float(v) for v in boxes.xyxy[i].tolist()]
            cls_id = int(boxes.cls[i].item())
            confidence = round(float(boxes.conf[i].item()), 3)
            det = {
                "class": names[cls_id],
                "bbox": [round(x1), round(y1), round(x2), round(y2)],
                "confidence": confidence,
            }
            if masks is not None and i < len(masks.xy):
                det["polygon"] = [[round(float(x)), round(float(y))] for x, y in masks.xy[i].tolist()]
            detections.append(det)

        return detections


@app.function(image=inference_image)
@modal.fastapi_endpoint(method="POST")
def infer(payload: dict) -> dict:
    """
    Body: {"sheetUrl": "https://...", "task": "rooms" | "symbols"}
    Returns: {"detections": [...], "status": "ok" | "error", "error"?: str}

    sheetUrl download uses plain requests.get rather than app/backend's
    storage.py (that module assumes a shared filesystem/boto3 session this
    isolated Modal container doesn't have) — pass a presigned/public URL,
    which is exactly what storage.generate_presigned_download() already
    produces on the caller's side.
    """
    import requests

    sheet_url = payload.get("sheetUrl")
    task = payload.get("task")
    if not sheet_url or task not in ("rooms", "symbols"):
        return {"detections": [], "status": "error", "error": "sheetUrl and task ('rooms'|'symbols') are required"}

    try:
        resp = requests.get(sheet_url, timeout=30)
        resp.raise_for_status()
        service = InferenceService()
        detections = service.infer.remote(resp.content, task)
        return {"detections": detections, "status": "ok"}
    except Exception as e:
        return {"detections": [], "status": "error", "error": str(e)}
