# Backend (FastAPI) image — the API/login/estimating service. Heavy ML (torch,
# ultralytics, cv2) is NOT installed here; it runs on the separate GPU inference
# image (ai/inference/Dockerfile). This image only needs to boot the API.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    ENVIRONMENT=production

WORKDIR /app

# tesseract-ocr enables title-block / scale OCR (degrades gracefully if absent).
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# `emergentintegrations` is unused (grep-verified) and not reliably resolvable on
# PyPI — drop it so the build is deterministic. Everything else the API imports
# at startup is installed.
RUN grep -v '^emergentintegrations' requirements.txt > requirements.runtime.txt \
    && pip install -r requirements.runtime.txt

COPY . .
RUN chmod +x start.sh

# Render/Fly inject $PORT; default 8000 for local `docker run`.
EXPOSE 8000
CMD ["./start.sh"]
