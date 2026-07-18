"""
TakeOff.ai — Scale Detection via OCR
Replaces the mock scale detection with real OCR + pattern matching.

Detects scale notations like:
  - "1/8" = 1'-0""
  - "1:96"
  - "Scale: 1/4" = 1'-0""
  - "1" = 20'"
  - Graphic scale bars (fallback)
"""

import re
import numpy as np
from typing import Optional
from loguru import logger


# ──────────────────────────────────────────────────────────────
# Scale notation patterns (imperial + metric)
# ──────────────────────────────────────────────────────────────

# Maps common architectural scale strings → scale ratio (paper inches per real inch)
# e.g. 1/8" = 1'-0" means 1/8 inch on paper = 12 inches real → ratio = 96
KNOWN_SCALES: dict[str, float] = {
    # Imperial architectural scales
    '3"=1\'-0"': 4,
    '1-1/2"=1\'-0"': 8,
    '1"=1\'-0"': 12,
    '3/4"=1\'-0"': 16,
    '1/2"=1\'-0"': 24,
    '3/8"=1\'-0"': 32,
    '1/4"=1\'-0"': 48,
    '3/16"=1\'-0"': 64,
    '1/8"=1\'-0"': 96,
    '3/32"=1\'-0"': 128,
    '1/16"=1\'-0"': 192,
    # Engineering scales (1 inch = N feet)
    '1"=5\'': 60,
    '1"=10\'': 120,
    '1"=20\'': 240,
    '1"=30\'': 360,
    '1"=40\'': 480,
    '1"=50\'': 600,
    '1"=60\'': 720,
    '1"=100\'': 1200,
    '1"=200\'': 2400,
}

# Regex patterns for OCR text → scale ratio
SCALE_PATTERNS = [
    # "1/8" = 1'-0""  or  "1/8"=1'-0""
    (
        re.compile(
            r'(\d+)/(\d+)\s*["\u201c\u201d]\s*[=:]\s*1\s*[\'\u2018\u2019]\s*[-\u2013]?\s*0\s*["\u201c\u201d]',
            re.IGNORECASE,
        ),
        "fraction_to_foot",
    ),
    # "1" = 10'" or "1"=20'"
    (
        re.compile(
            r'1\s*["\u201c\u201d]\s*[=:]\s*(\d+)\s*[\'\u2018\u2019]',
            re.IGNORECASE,
        ),
        "inch_to_feet",
    ),
    # "1:96" or "1 : 96" (ratio notation)
    (
        re.compile(r'1\s*:\s*(\d+)', re.IGNORECASE),
        "ratio",
    ),
    # "Scale 1/8" or "Scale: 1/4"" — looser match
    (
        re.compile(
            r'scale\s*[:\s]\s*(\d+)/(\d+)',
            re.IGNORECASE,
        ),
        "scale_fraction",
    ),
]


def _normalize_text(text: str) -> str:
    """Normalize OCR text: remove noise, standardize quotes."""
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _fraction_to_scale_ratio(numerator: int, denominator: int) -> float:
    """
    Given fraction N/D representing paper inches per foot:
    scale_ratio = 12 * (denominator / numerator)
    e.g. 1/8 → 12 * 8/1 = 96
    """
    return 12.0 * denominator / numerator


def _inch_to_feet_ratio(feet: float) -> float:
    """1 inch on paper = `feet` feet in reality → ratio = feet * 12"""
    return feet * 12.0


def parse_scale_from_text(ocr_results: list[dict]) -> Optional[dict]:
    """
    Search OCR results for a scale notation.

    Args:
        ocr_results: List of {text, bbox, confidence} dicts from OCR engine.

    Returns:
        {
          'ratio': float,        # paper pixels-per-real-inch scale factor
          'text': str,           # original matched text
          'confidence': float,   # OCR confidence of matched line
          'bbox': list,          # where on the image the scale was found
        }
        or None if not found.
    """
    # Combine all OCR text with context — scale often spans tokens
    full_text = " ".join(r.get("text", "") for r in ocr_results)
    full_text = _normalize_text(full_text)
    logger.debug(f"OCR full text (first 500 chars): {full_text[:500]}")

    best_match = None

    for result in ocr_results:
        raw = _normalize_text(result.get("text", ""))
        if not raw:
            continue

        # Try each regex pattern
        for pattern, pattern_type in SCALE_PATTERNS:
            m = pattern.search(raw)
            if not m:
                continue

            ratio: Optional[float] = None

            if pattern_type == "fraction_to_foot":
                num, den = int(m.group(1)), int(m.group(2))
                if num > 0 and den > 0:
                    ratio = _fraction_to_scale_ratio(num, den)

            elif pattern_type == "inch_to_feet":
                feet = float(m.group(1))
                ratio = _inch_to_feet_ratio(feet)

            elif pattern_type == "ratio":
                ratio = float(m.group(1))

            elif pattern_type == "scale_fraction":
                num, den = int(m.group(1)), int(m.group(2))
                if num > 0 and den > 0:
                    ratio = _fraction_to_scale_ratio(num, den)

            if ratio and 1 < ratio < 10000:  # sanity check
                conf = result.get("confidence", 0.0)
                if best_match is None or conf > best_match["confidence"]:
                    best_match = {
                        "ratio": ratio,
                        "text": raw,
                        "confidence": conf,
                        "bbox": result.get("bbox"),
                        "pattern_type": pattern_type,
                    }
                    logger.info(
                        f"Scale found: '{raw}' → ratio={ratio:.1f} "
                        f"(conf={conf:.2f}, type={pattern_type})"
                    )
                    break  # found a match, move to next OCR result

    return best_match


def detect_scale_bar(img: np.ndarray) -> Optional[float]:
    """
    Fallback: detect a graphic scale bar in the image.

    Strategy:
      1. Look for horizontal lines of consistent thickness in the lower portion of the drawing
      2. Find tick marks at ends
      3. If there's text nearby (from OCR), try to match distance to label

    This is a rough heuristic — use only when OCR scale text not found.
    Returns estimated scale_ratio or None.
    """
    import cv2  # lazy: keeps the module (and its pure text helpers, imported by
                # routes/scale_routes.py) usable without OpenCV installed.
    height, width = img.shape[:2]

    # Focus on the bottom 20% of the image (where scale bars usually live)
    roi = img[int(height * 0.75):, :]

    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)

    # Detect horizontal lines
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180,
        threshold=100,
        minLineLength=int(width * 0.03),   # at least 3% of image width
        maxLineGap=5,
    )

    if lines is None:
        return None

    # Filter near-horizontal lines
    horizontal = []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        angle = abs(np.degrees(np.arctan2(y2 - y1, x2 - x1)))
        if angle < 5:  # within 5° of horizontal
            length = abs(x2 - x1)
            horizontal.append((x1, y1, x2, y2, length))

    if not horizontal:
        return None

    # Sort by length descending — scale bar is usually one of the longer lines
    horizontal.sort(key=lambda l: l[4], reverse=True)

    # Can't reliably compute ratio without the label — return None
    # (the OCR parse_scale_from_text should have already caught this)
    logger.debug(f"Scale bar detected ({len(horizontal)} candidates) but no label matched")
    return None


def run_ocr_for_scale(img: np.ndarray) -> Optional[dict]:
    """
    Run PaddleOCR on the image and extract scale information.

    This is the main entry point called by the pipeline.
    Falls back to scale bar detection if OCR finds nothing.

    Returns same dict as parse_scale_from_text, plus:
        'method': 'ocr_text' | 'scale_bar' | 'default'
    """
    try:
        from paddleocr import PaddleOCR
        ocr_engine = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)

        result = ocr_engine.ocr(img, cls=True)
        if not result or not result[0]:
            logger.warning("OCR returned no results")
            return _default_scale()

        # Flatten PaddleOCR output → list of {text, bbox, confidence}
        flat: list[dict] = []
        for line in result:
            if not line:
                continue
            for item in line:
                bbox, (text, conf) = item
                flat.append({
                    "bbox": bbox,
                    "text": text,
                    "confidence": float(conf),
                })

        scale = parse_scale_from_text(flat)
        if scale:
            scale["method"] = "ocr_text"
            return scale

        # Fallback: graphic scale bar
        bar_ratio = detect_scale_bar(img)
        if bar_ratio:
            return {
                "ratio": bar_ratio,
                "text": f"scale bar ~1:{bar_ratio:.0f}",
                "confidence": 0.5,
                "method": "scale_bar",
            }

    except ImportError:
        logger.warning("PaddleOCR not installed — using default scale")
    except Exception as e:
        logger.error(f"OCR failed: {e}")

    return _default_scale()


def _default_scale() -> dict:
    """Return 1/8"=1'-0" (ratio=96) as the most common architectural scale."""
    return {
        "ratio": 96.0,
        "text": "default: 1/8\"=1'-0\"",
        "confidence": 0.0,
        "method": "default",
    }


def scale_ratio_to_string(ratio: float) -> str:
    """Convert numeric ratio back to human-readable scale string."""
    for label, r in KNOWN_SCALES.items():
        if abs(r - ratio) < 0.5:
            return label
    # Best approximate match
    feet_per_inch = ratio / 12
    if feet_per_inch < 1:
        return f'1/{int(1/feet_per_inch)}"=1\'-0"'
    return f'1"={feet_per_inch:.0f}\''