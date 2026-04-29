"""
TakeOff.ai — Celery Task Queue for AI Jobs

AI inference takes 2–30 seconds. It MUST run in a background worker,
never in the FastAPI request thread.

Architecture:
  FastAPI → enqueue task → Redis broker → Celery worker → result stored in DB

Start workers:
  celery -A ai_tasks worker --loglevel=info --concurrency=2 -Q ai_inference

Monitor:
  celery -A ai_tasks flower --port=5555
"""

import os
import json
import time
from pathlib import Path
from celery import Celery
from loguru import logger


# ──────────────────────────────────────────────────────────────
# Celery app setup
# ──────────────────────────────────────────────────────────────
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

app = Celery(
    "takeoffai",
    broker=REDIS_URL,
    backend=REDIS_URL,
)

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    result_expires=3600,            # results kept 1 hour
    task_soft_time_limit=120,       # 2 min soft limit per task
    task_time_limit=180,            # 3 min hard limit
    worker_prefetch_multiplier=1,   # one task at a time per worker (AI jobs are heavy)
    task_acks_late=True,            # re-queue on worker crash
    task_reject_on_worker_lost=True,
    task_routes={
        "ai_tasks.run_ai_analysis": {"queue": "ai_inference"},
        "ai_tasks.index_drawing_for_search": {"queue": "ai_inference"},
        "ai_tasks.run_ocr_extraction": {"queue": "ai_inference"},
    },
)


# ──────────────────────────────────────────────────────────────
# Lazy-loaded AI components (not imported at module level —
# importing YOLO at module level is slow and wastes memory on web workers)
# ──────────────────────────────────────────────────────────────
_detector = None
_ocr_engine = None
_clip_model = None


def _get_detector():
    global _detector
    if _detector is None:
        from detection_engine import BlueprintDetector
        _detector = BlueprintDetector()
    return _detector


def _get_ocr():
    global _ocr_engine
    if _ocr_engine is None:
        from scale_detection import run_ocr_for_scale
        _ocr_engine = run_ocr_for_scale
    return _ocr_engine


# ──────────────────────────────────────────────────────────────
# Task 1: Full AI analysis of a drawing
# ──────────────────────────────────────────────────────────────
@app.task(bind=True, name="ai_tasks.run_ai_analysis", max_retries=2)
def run_ai_analysis(self, drawing_id: int, file_path: str) -> dict:
    """
    Main AI pipeline task. Called after a drawing is uploaded.

    Args:
        drawing_id: DB id of the Drawing record.
        file_path:  Local path or S3 URI of the drawing file.

    Returns:
        detection results dict (saved to TakeoffResult table by caller).
    """
    logger.info(f"[Task {self.request.id}] Starting AI analysis for drawing {drawing_id}")
    t_start = time.time()

    try:
        # Import here to avoid loading YOLO on web workers
        from preprocessing import load_drawing
        from scale_detection import run_ocr_for_scale

        # Handle S3 paths
        local_path = _resolve_path(file_path)

        # 1. Load + preprocess
        logger.info(f"Loading drawing: {local_path}")
        img = load_drawing(local_path, page_number=0)
        logger.info(f"Image loaded: {img.shape}")

        # 2. Detect scale (OCR)
        logger.info("Running scale detection...")
        scale_info = run_ocr_for_scale(img)
        logger.info(f"Scale: {scale_info}")

        # 3. Run AI detection
        logger.info("Running YOLO detection...")
        detector = _get_detector()
        detection_result = detector.detect(img, scale_info=scale_info)
        detection_result["drawing_id"] = drawing_id
        detection_result["scale_info"] = scale_info

        elapsed_ms = int((time.time() - t_start) * 1000)
        detection_result["total_processing_ms"] = elapsed_ms

        logger.info(
            f"[Task {self.request.id}] Analysis complete: "
            f"{detection_result['summary']['rooms']} rooms, "
            f"{detection_result['summary']['doors']} doors, "
            f"{detection_result['summary']['windows']} windows | "
            f"{elapsed_ms}ms"
        )

        return detection_result

    except FileNotFoundError as exc:
        logger.error(f"Model not trained yet: {exc}")
        # Don't retry — user needs to train first
        raise exc

    except Exception as exc:
        logger.error(f"AI analysis failed (attempt {self.request.retries + 1}): {exc}")
        raise self.retry(exc=exc, countdown=30)  # retry after 30s

    finally:
        # Clean up temporary S3 download
        if file_path.startswith("s3://") and Path(local_path).exists():
            Path(local_path).unlink(missing_ok=True)


# ──────────────────────────────────────────────────────────────
# Task 2: Index drawing for AI Image + Text Search
# ──────────────────────────────────────────────────────────────
@app.task(bind=True, name="ai_tasks.index_drawing_for_search", max_retries=1)
def index_drawing_for_search(self, drawing_id: int, file_path: str) -> dict:
    """
    Build search index for a drawing:
      - CLIP embeddings for AI Image Search (patch-level)
      - OCR text extraction for AI Text Search (full-text index)

    Both are stored in PostgreSQL (pgvector for CLIP, tsvector for OCR).
    """
    logger.info(f"[Task {self.request.id}] Indexing drawing {drawing_id} for search")

    try:
        from preprocessing import load_drawing, extract_patches, preprocess_for_clip

        local_path = _resolve_path(file_path)
        img = load_drawing(local_path, page_number=0)

        results = {
            "drawing_id": drawing_id,
            "clip_patches": 0,
            "ocr_words": 0,
        }

        # CLIP patch embeddings
        try:
            import clip
            import torch
            from PIL import Image as PILImage

            device = "cuda" if torch.cuda.is_available() else "cpu"
            clip_model, clip_preprocess = clip.load("ViT-B/32", device=device)

            patches, coords = extract_patches(img, patch_size=224, stride=112)
            embeddings = []

            batch_size = 32
            for i in range(0, len(patches), batch_size):
                batch = patches[i:i+batch_size]
                pil_batch = [PILImage.fromarray(p[:, :, ::-1]) for p in batch]  # BGR→RGB
                tensors = torch.stack([clip_preprocess(p) for p in pil_batch]).to(device)

                with torch.no_grad():
                    embs = clip_model.encode_image(tensors)
                    embs = embs / embs.norm(dim=-1, keepdim=True)  # normalize
                    embeddings.extend(embs.cpu().numpy().tolist())

            results["clip_patches"] = len(embeddings)
            results["clip_embeddings"] = embeddings
            results["clip_coords"] = coords
            logger.info(f"CLIP: indexed {len(embeddings)} patches")

        except ImportError:
            logger.warning("CLIP not installed — skipping image search indexing")

        # OCR text extraction
        try:
            from paddleocr import PaddleOCR
            ocr = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
            ocr_result = ocr.ocr(img, cls=True)

            words = []
            if ocr_result and ocr_result[0]:
                for line in ocr_result:
                    if not line:
                        continue
                    for item in line:
                        bbox, (text, conf) = item
                        words.append({
                            "text": text,
                            "confidence": float(conf),
                            "bbox": [[int(p[0]), int(p[1])] for p in bbox],
                        })

            results["ocr_words"] = len(words)
            results["ocr_data"] = words
            logger.info(f"OCR: extracted {len(words)} text elements")

        except ImportError:
            logger.warning("PaddleOCR not installed — skipping text search indexing")

        return results

    except Exception as exc:
        logger.error(f"Indexing failed: {exc}")
        raise self.retry(exc=exc, countdown=60)


# ──────────────────────────────────────────────────────────────
# Task 3: OCR-only extraction (lighter than full index)
# ──────────────────────────────────────────────────────────────
@app.task(bind=True, name="ai_tasks.run_ocr_extraction", max_retries=1)
def run_ocr_extraction(self, drawing_id: int, file_path: str) -> dict:
    """
    Run OCR on a drawing and return raw text elements.
    Used for: auto drawing naming, scale detection, dimension extraction.
    """
    logger.info(f"[Task {self.request.id}] OCR extraction for drawing {drawing_id}")

    try:
        from preprocessing import load_drawing
        from scale_detection import run_ocr_for_scale

        local_path = _resolve_path(file_path)
        img = load_drawing(local_path, page_number=0)

        scale_info = run_ocr_for_scale(img)

        # Try to extract drawing name/title from title block
        drawing_name = _extract_drawing_name(scale_info.get("_all_text", []))

        return {
            "drawing_id": drawing_id,
            "scale_info": scale_info,
            "suggested_name": drawing_name,
        }

    except Exception as exc:
        logger.error(f"OCR extraction failed: {exc}")
        raise self.retry(exc=exc, countdown=30)


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────
def _resolve_path(file_path: str) -> str:
    """Download S3 file to /tmp if needed, return local path."""
    if not file_path.startswith("s3://"):
        return file_path

    import boto3
    import tempfile

    # Parse s3://bucket/key
    parts = file_path[5:].split("/", 1)
    bucket, key = parts[0], parts[1]

    suffix = Path(key).suffix
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.close()

    logger.info(f"Downloading s3://{bucket}/{key} → {tmp.name}")
    s3 = boto3.client("s3")
    s3.download_file(bucket, key, tmp.name)
    return tmp.name


def _extract_drawing_name(ocr_texts: list) -> str:
    """
    Try to extract drawing sheet name/number from OCR text.
    Title blocks usually contain patterns like "A-101", "LEVEL 12", etc.
    """
    import re

    sheet_pattern = re.compile(r'[A-Z]{1,2}[-\s]?\d{3,4}', re.IGNORECASE)
    level_pattern = re.compile(r'level\s+\d+|floor\s+\d+|basement|ground|roof', re.IGNORECASE)

    for item in ocr_texts:
        text = item.get("text", "") if isinstance(item, dict) else str(item)
        if sheet_pattern.search(text):
            return text.strip()
        if level_pattern.search(text):
            return text.strip().title()

    return ""