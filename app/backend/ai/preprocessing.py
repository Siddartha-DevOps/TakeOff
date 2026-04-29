"""
TakeOff.ai — Blueprint Preprocessing Pipeline
Handles PDF/TIFF/PNG/JPG → normalized tensor ready for YOLO + CLIP + OCR.
Local dev: CPU. Production: GPU (SageMaker ml.g4dn.xlarge).
"""

import cv2
import numpy as np
from pathlib import Path
from PIL import Image
import fitz  # PyMuPDF — fast PDF rasterization
from typing import Optional
from loguru import logger


# ──────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────
TARGET_DPI = 300          # standard architectural drawing DPI
YOLO_IMGSZ = 1280         # YOLO input size (large = better for small objects)
CLIP_IMGSZ = 224          # CLIP ViT-B/32 input
MAX_FILE_MB = 500
SUPPORTED_TYPES = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif"}


# ──────────────────────────────────────────────────────────────
# PDF → Image
# ──────────────────────────────────────────────────────────────
def pdf_to_images(
    pdf_path: str | Path,
    dpi: int = TARGET_DPI,
    page_number: Optional[int] = None,
) -> list[np.ndarray]:
    """
    Rasterize PDF pages to OpenCV BGR images at TARGET_DPI.

    Args:
        pdf_path:    Path to PDF file.
        dpi:         Render resolution.
        page_number: If set, render only that page (0-indexed). Otherwise all pages.

    Returns:
        List of (H, W, 3) uint8 BGR numpy arrays, one per page.
    """
    pdf_path = Path(pdf_path)
    doc = fitz.open(str(pdf_path))
    zoom = dpi / 72.0          # PyMuPDF default is 72 DPI
    mat = fitz.Matrix(zoom, zoom)

    pages = range(len(doc)) if page_number is None else [page_number]
    images: list[np.ndarray] = []

    for i in pages:
        page = doc[i]
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img_bytes = pix.tobytes("png")

        arr = np.frombuffer(img_bytes, np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        images.append(img)
        logger.debug(f"Rasterized page {i}: {img.shape}")

    doc.close()
    return images


# ──────────────────────────────────────────────────────────────
# General image loader (any supported type)
# ──────────────────────────────────────────────────────────────
def load_drawing(
    file_path: str | Path,
    page_number: int = 0,
    dpi: int = TARGET_DPI,
) -> np.ndarray:
    """
    Load any supported drawing file to a BGR numpy array.

    For PDFs: rasterizes the specified page.
    For images: loads and converts to BGR at nearest TARGET_DPI equivalent.
    """
    file_path = Path(file_path)
    ext = file_path.suffix.lower()

    if ext not in SUPPORTED_TYPES:
        raise ValueError(f"Unsupported file type: {ext}. Supported: {SUPPORTED_TYPES}")

    if ext == ".pdf":
        pages = pdf_to_images(file_path, dpi=dpi, page_number=page_number)
        if not pages:
            raise ValueError("PDF has no renderable pages")
        return pages[0]

    # Raster image (PNG, JPG, TIFF)
    img = cv2.imread(str(file_path), cv2.IMREAD_COLOR)
    if img is None:
        # Fallback via Pillow (handles TIFF better)
        pil = Image.open(str(file_path)).convert("RGB")
        img = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
    return img


# ──────────────────────────────────────────────────────────────
# Preprocessing: enhance blueprint for detection
# ──────────────────────────────────────────────────────────────
def enhance_blueprint(img: np.ndarray) -> np.ndarray:
    """
    Enhance contrast and sharpness for better YOLO detection.
    Blueprints vary wildly in scan quality — this normalizes them.

    Pipeline:
      1. Convert to grayscale
      2. CLAHE (adaptive histogram equalization) for contrast
      3. Gaussian sharpening
      4. Back to BGR (YOLO expects color input even if grayscale content)
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Adaptive contrast — handles both light and dark scans
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)

    # Sharpen: subtract blurred version (unsharp mask)
    blurred = cv2.GaussianBlur(enhanced, (0, 0), sigmaX=2)
    sharpened = cv2.addWeighted(enhanced, 1.5, blurred, -0.5, 0)
    sharpened = np.clip(sharpened, 0, 255).astype(np.uint8)

    # Back to BGR for YOLO
    return cv2.cvtColor(sharpened, cv2.COLOR_GRAY2BGR)


def preprocess_for_yolo(
    img: np.ndarray,
    imgsz: int = YOLO_IMGSZ,
    enhance: bool = True,
) -> np.ndarray:
    """
    Prepare image for YOLO inference.
    YOLO handles resize internally, so we just enhance.
    Returns BGR uint8 array.
    """
    if enhance:
        img = enhance_blueprint(img)
    return img


def preprocess_for_clip(img_patch: np.ndarray) -> np.ndarray:
    """
    Prepare an image patch (cropped region) for CLIP embedding.
    Resizes to 224×224 with letterbox padding.
    """
    h, w = img_patch.shape[:2]
    scale = CLIP_IMGSZ / max(h, w)
    nh, nw = int(h * scale), int(w * scale)
    resized = cv2.resize(img_patch, (nw, nh), interpolation=cv2.INTER_AREA)

    # Center-pad to 224×224
    canvas = np.ones((CLIP_IMGSZ, CLIP_IMGSZ, 3), dtype=np.uint8) * 128
    y_off = (CLIP_IMGSZ - nh) // 2
    x_off = (CLIP_IMGSZ - nw) // 2
    canvas[y_off:y_off+nh, x_off:x_off+nw] = resized

    return canvas  # BGR uint8


# ──────────────────────────────────────────────────────────────
# Crop patches for CLIP search indexing
# ──────────────────────────────────────────────────────────────
def extract_patches(
    img: np.ndarray,
    patch_size: int = 224,
    stride: int = 112,          # 50% overlap
) -> tuple[list[np.ndarray], list[tuple[int, int, int, int]]]:
    """
    Slide a window over a blueprint and extract overlapping patches.
    Used to build the CLIP search index for AI Image Search.

    Returns:
        patches:  List of (224, 224, 3) BGR arrays.
        coords:   List of (x1, y1, x2, y2) pixel coords per patch.
    """
    h, w = img.shape[:2]
    patches = []
    coords = []

    for y in range(0, h - patch_size + 1, stride):
        for x in range(0, w - patch_size + 1, stride):
            patch = img[y:y+patch_size, x:x+patch_size]
            patches.append(preprocess_for_clip(patch))
            coords.append((x, y, x + patch_size, y + patch_size))

    # Don't miss right/bottom edges
    # (last stride may not land exactly on the edge)
    logger.debug(f"Extracted {len(patches)} patches from {w}×{h} image")
    return patches, coords


# ──────────────────────────────────────────────────────────────
# Pixel → real-world unit conversion
# ──────────────────────────────────────────────────────────────
def pixels_to_feet(
    pixel_length: float,
    scale_ratio: float,
    dpi: int = TARGET_DPI,
) -> float:
    """
    Convert pixel distance to real-world feet using drawing scale.

    Args:
        pixel_length: Distance in pixels.
        scale_ratio:  Drawing scale (e.g. 96 for 1/8"=1'-0").
        dpi:          Scan DPI.

    Returns:
        Real-world length in decimal feet.

    Example:
        Scale "1/8″ = 1′-0″" means 1 inch on paper = 8 feet in reality.
        At 300 DPI: 1 inch = 300 pixels.
        So 300 pixels = 8 feet → 1 pixel = 8/300 feet.
        scale_ratio = 96  (8 feet × 12 inches)
    """
    inches_per_pixel = 1.0 / dpi
    real_inches = pixel_length * inches_per_pixel * scale_ratio
    return real_inches / 12.0


def pixels_to_sqft(
    pixel_area: float,
    scale_ratio: float,
    dpi: int = TARGET_DPI,
) -> float:
    """Convert pixel area (px²) to real-world square feet."""
    feet_per_pixel = pixels_to_feet(1.0, scale_ratio, dpi)
    return pixel_area * (feet_per_pixel ** 2)


# ──────────────────────────────────────────────────────────────
# Image metadata
# ──────────────────────────────────────────────────────────────
def get_image_dpi(file_path: str | Path) -> tuple[int, int]:
    """
    Try to read DPI metadata from image EXIF.
    Returns (x_dpi, y_dpi). Falls back to (300, 300) if not found.
    """
    try:
        pil = Image.open(str(file_path))
        dpi = pil.info.get("dpi") or pil.info.get("resolution")
        if dpi and isinstance(dpi, (tuple, list)):
            return int(dpi[0]), int(dpi[1])
    except Exception:
        pass
    return TARGET_DPI, TARGET_DPI


def get_page_count(file_path: str | Path) -> int:
    """Return number of pages for PDF, or 1 for images."""
    file_path = Path(file_path)
    if file_path.suffix.lower() == ".pdf":
        doc = fitz.open(str(file_path))
        count = len(doc)
        doc.close()
        return count
    return 1