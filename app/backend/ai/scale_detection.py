"""Safe scale candidate extraction for construction drawings.

Detection and trust are intentionally separate: OCR/vector text may suggest a
scale, but only the scale routes may promote it after conflict and DPI checks.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
from loguru import logger

KNOWN_SCALES: dict[str, float] = {
    '3"=1\'-0"': 4, '1-1/2"=1\'-0"': 8, '1"=1\'-0"': 12,
    '3/4"=1\'-0"': 16, '1/2"=1\'-0"': 24, '3/8"=1\'-0"': 32,
    '1/4"=1\'-0"': 48, '3/16"=1\'-0"': 64, '1/8"=1\'-0"': 96,
    '3/32"=1\'-0"': 128, '1/16"=1\'-0"': 192,
    '1"=5\'': 60, '1"=10\'': 120, '1"=20\'': 240, '1"=30\'': 360,
    '1"=40\'': 480, '1"=50\'': 600, '1"=60\'': 720,
    '1"=100\'': 1200, '1"=200\'': 2400,
}

MIN_SCALE_RATIO = 2.0
MAX_SCALE_RATIO = 10000.0
CONFLICT_RELATIVE_TOLERANCE = 0.02

_IMPERIAL_FRACTION_RE = re.compile(
    r"(?P<num>\d+)\s*/\s*(?P<den>\d+)\s*[\"“”]\s*[=:]\s*"
    r"(?P<feet>\d+(?:\.\d+)?)\s*['‘’]\s*(?:[-–]\s*0\s*[\"“”])?", re.I,
)
_IMPERIAL_INCH_RE = re.compile(
    r"1\s*[\"“”]\s*[=:]\s*(?P<feet>\d+(?:\.\d+)?)\s*['‘’]", re.I,
)
_RATIO_RE = re.compile(
    r"(?:\bscale\s*[:=]?\s*)?\b1\s*:\s*(?P<ratio>\d+(?:\.\d+)?)\b", re.I,
)
_LOOSE_SCALE_FRACTION_RE = re.compile(
    r"\bscale\s*[:=]?\s*(?P<num>\d+)\s*/\s*(?P<den>\d+)\s*[\"“”]?", re.I,
)


def _normalize_text(text: str) -> str:
    text = str(text or "").replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    return re.sub(r"\s+", " ", text).strip()


def _valid_ratio(value: object) -> Optional[float]:
    try:
        ratio = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(ratio) or not (MIN_SCALE_RATIO <= ratio <= MAX_SCALE_RATIO):
        return None
    return ratio


def _method_for(text: str, bbox, image_shape, base_method: str) -> str:
    prefix = "pdf_vector" if base_method == "pdf_vector_text" else "ocr"
    if re.search(r"\bscale\b", text, re.I):
        return f"title_block_{prefix}"
    if bbox and image_shape and len(image_shape) >= 2:
        height, width = image_shape[:2]
        try:
            points = bbox if isinstance(bbox[0], (list, tuple)) else [bbox[:2], bbox[2:4]]
            cx = sum(float(point[0]) for point in points) / len(points)
            cy = sum(float(point[1]) for point in points) / len(points)
            if cx >= width * 0.62 and cy >= height * 0.68:
                return f"title_block_{prefix}"
        except (TypeError, ValueError, IndexError, ZeroDivisionError):
            pass
    return f"{prefix}_text"


def _matches(text: str) -> Iterable[tuple[float, str, str]]:
    for match in _IMPERIAL_FRACTION_RE.finditer(text):
        num, den = int(match.group("num")), int(match.group("den"))
        feet = float(match.group("feet"))
        if num and den and feet > 0:
            yield 12.0 * feet * den / num, match.group(0), "imperial_fraction"
    for match in _IMPERIAL_INCH_RE.finditer(text):
        feet = float(match.group("feet"))
        if feet > 0:
            yield feet * 12.0, match.group(0), "imperial_engineering"
    for match in _RATIO_RE.finditer(text):
        yield float(match.group("ratio")), match.group(0), "metric_or_ratio"
    for match in _LOOSE_SCALE_FRACTION_RE.finditer(text):
        num, den = int(match.group("num")), int(match.group("den"))
        if num and den:
            yield 12.0 * den / num, match.group(0), "imperial_scale_fraction"


def parse_scale_candidates(
    text_results: list[dict], *, image_shape=None, base_method: str = "ocr"
) -> list[dict]:
    """Return every distinct valid scale candidate with its evidence."""
    candidates: list[dict] = []
    fragments: list[str] = []
    confidences: list[float] = []
    for result in text_results:
        raw = _normalize_text(result.get("text", ""))
        if not raw:
            continue
        fragments.append(raw)
        confidence = max(0.0, min(1.0, float(result.get("confidence", 0.0) or 0.0)))
        confidences.append(confidence)
        for ratio, notation, pattern_type in _matches(raw):
            ratio = _valid_ratio(ratio)
            if ratio is not None:
                candidates.append({
                    "ratio": ratio, "text": notation, "raw_text": raw,
                    "confidence": confidence, "bbox": result.get("bbox"),
                    "pattern_type": pattern_type,
                    "method": _method_for(raw, result.get("bbox"), image_shape, base_method),
                })

    # OCR frequently splits `SCALE`, `1:`, and `100` into separate tokens.
    joined = _normalize_text(" ".join(fragments))
    if joined:
        for ratio, notation, pattern_type in _matches(joined):
            ratio = _valid_ratio(ratio)
            if ratio is not None:
                candidates.append({
                    "ratio": ratio, "text": notation, "raw_text": joined,
                    "confidence": min(confidences or [0.0]), "bbox": None,
                    "pattern_type": pattern_type,
                    "method": _method_for(joined, None, image_shape, base_method),
                })

    distinct: list[dict] = []
    for candidate in sorted(candidates, key=lambda item: item["confidence"], reverse=True):
        duplicate = next((item for item in distinct if (
            abs(item["ratio"] - candidate["ratio"]) / max(item["ratio"], candidate["ratio"])
            <= CONFLICT_RELATIVE_TOLERANCE
        )), None)
        if duplicate is None:
            distinct.append(candidate)
        elif candidate["method"].startswith("title_block") and not duplicate["method"].startswith("title_block"):
            distinct[distinct.index(duplicate)] = candidate
    return distinct


def select_scale_candidate(candidates: list[dict]) -> Optional[dict]:
    """Rank candidates while explicitly preserving disagreement."""
    if not candidates:
        return None
    ranked = sorted(candidates, key=lambda item: (
        item.get("method", "").startswith("title_block"),
        float(item.get("confidence", 0.0)),
    ), reverse=True)
    best = dict(ranked[0])
    conflict = any(
        abs(best["ratio"] - item["ratio"]) / max(best["ratio"], item["ratio"])
        > CONFLICT_RELATIVE_TOLERANCE
        for item in ranked[1:]
    )
    best.update({
        "conflict": conflict, "requires_confirmation": True,
        "candidates": [{key: item.get(key) for key in (
            "ratio", "text", "confidence", "method", "pattern_type"
        )} for item in ranked],
    })
    return best


def parse_scale_from_text(ocr_results: list[dict]) -> Optional[dict]:
    return select_scale_candidate(parse_scale_candidates(ocr_results))


def extract_pdf_scale_candidates(pdf_path: str | Path, page_number: int = 0) -> list[dict]:
    """Read scale text directly from exactly one vector PDF page."""
    import fitz
    with fitz.open(str(pdf_path)) as document:
        if page_number < 0 or page_number >= document.page_count:
            raise ValueError(f"PDF page {page_number} is out of range")
        page = document.load_page(page_number)
        results = [{
            "text": _normalize_text(block[4]),
            "bbox": [block[0], block[1], block[2], block[3]], "confidence": 1.0,
        } for block in page.get_text("blocks") if _normalize_text(block[4])]
        return parse_scale_candidates(
            results, image_shape=(float(page.rect.height), float(page.rect.width)),
            base_method="pdf_vector_text",
        )


def detect_scale_bar(img: np.ndarray) -> bool:
    """Detect likely scale-bar linework without inventing a ratio."""
    import cv2
    height, width = img.shape[:2]
    gray = cv2.cvtColor(img[int(height * 0.75):, :], cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    lines = cv2.HoughLinesP(
        edges, 1, np.pi / 180, 100,
        minLineLength=max(10, int(width * 0.03)), maxLineGap=5,
    )
    if lines is None:
        return False
    return any(abs(np.degrees(np.arctan2(
        line[0][3] - line[0][1], line[0][2] - line[0][0]
    ))) < 5 for line in lines)


def run_ocr_for_scale(img: np.ndarray) -> Optional[dict]:
    """OCR a raster and return a candidate; never return a default scale."""
    try:
        from paddleocr import PaddleOCR
        result = PaddleOCR(use_angle_cls=True, lang="en", show_log=False).ocr(img, cls=True)
        flat = []
        for line in result or []:
            for item in line or []:
                bbox, (text, confidence) = item
                flat.append({"bbox": bbox, "text": text, "confidence": float(confidence)})
        selected = select_scale_candidate(parse_scale_candidates(flat, image_shape=img.shape))
        if selected:
            return selected
        if detect_scale_bar(img):
            logger.info("Graphic scale bar detected, but no safe labeled ratio was recoverable")
            return {
                "ratio": None, "text": "graphic scale bar detected", "raw_text": "",
                "confidence": 0.25, "method": "scale_bar_unresolved", "conflict": False,
                "requires_confirmation": True, "candidates": [],
            }
    except ImportError:
        logger.warning("PaddleOCR not installed; automatic raster scale detection unavailable")
    except Exception as exc:
        logger.error(f"Scale OCR failed: {exc}")
    return None


def scale_ratio_to_string(ratio: float) -> str:
    ratio = float(ratio)
    for label, known in KNOWN_SCALES.items():
        if abs(known - ratio) < 0.5:
            return label
    return f"1:{ratio:.3f}".rstrip("0").rstrip(".")
