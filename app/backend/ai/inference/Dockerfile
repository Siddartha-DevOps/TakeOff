# GPU inference service image for TakeOff.ai (CLAUDE.md guardrail #1/#2:
# heavy CV runs on a separate GPU service, never inside a Vercel function).
#
# Base: CUDA 12.1 runtime + cuDNN. For a CPU-only deployment, swap the base for
# `python:3.11-slim` and drop the CUDA env — the same code runs (device.py
# resolves to CPU automatically).
FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TORCH_HOME=/models/torch \
    AI_MODEL_PATH=/models/best.pt

# System deps: python, and the OpenCV/PyMuPDF runtime libs + tesseract for OCR.
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.11 python3-pip \
        libgl1 libglib2.0-0 tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Heavy ML runtime — kept OUT of the app's requirements.txt / CI (those stay
# CPU-light). This image is where torch + ultralytics actually live.
RUN pip3 install --no-cache-dir \
        torch --index-url https://download.pytorch.org/whl/cu121 \
    && pip3 install --no-cache-dir \
        ultralytics opencv-python-headless numpy shapely pymupdf pillow pytesseract

# App code (the inference package + its geometry/OCR siblings).
COPY . /app/

# Weights are mounted at runtime (a volume or an init-container that pulls from
# the model registry), never baked into the image:
#   docker run --gpus all -v /host/models:/models takeoff-inference
VOLUME ["/models"]

# Smoke check: the package imports and reports device without a GPU present.
RUN python3 -c "from ai.inference import InferenceEngine; print('inference import OK')"

# Default: run the FastAPI inference surface. Override for a worker/benchmark.
CMD ["python3", "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
