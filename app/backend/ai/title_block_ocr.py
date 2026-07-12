"""
TakeOff.ai — Title-block OCR: sheet number, discipline, sheet title.

Closes memory/TOGAL_PARITY_REAUDIT.md #13's naming half: "OCR title block
to name/number/organize" (the splitting half lives in routes/upload_routes.py's
ingest_plan_set()). memory/TOGAL_GAP_ANALYSIS.md #13 names the three fields
Togal's auto-naming extracts per sheet: sheet number, sheet name, discipline
— this module extracts exactly those three, never fabricating a value it
didn't actually read (a None here means "OCR didn't find one", surfaced to
the UI as a numbered placeholder, not a guess presented as fact).

Uses pytesseract, not PaddleOCR — see app/requirements.txt's comment next
to pytesseract for why this one module diverges from CLAUDE.md §3's
"PaddleOCR for text": PaddleOCR needs a runtime model-weight download,
confirmed network-blocked in this project's sandbox this session (same as
CLIP's weights); pytesseract's tesseract-ocr binary ships its language
data locally, so this feature can actually be built and verified rather
than left as unverifiable, network-dependent code, at the cost of the
extra dependency this codebase's OCR story didn't previously have. Fully
optional/graceful-degrading like every other heavy dependency in this
backend (ai/detection_engine.py, ai/scale_detection.py, drawing_compare.py,
tiling.py) — a missing tesseract-ocr binary or pytesseract package means
identify_sheet() returns the numbered-placeholder fallback, never a crash.
"""

import re
from typing import Optional

# AIA Uniform Drawing System discipline-designator convention (the leading
# letter(s) of a sheet number): first match wins, so "AD-101" resolves to
# "AD" (existing/demo) before falling through to "A" alone.
DISCIPLINE_CODES = [
    "AD", "AS",              # existing/demolition, architectural site
    "A", "S", "C", "L", "M", "E", "P", "FP", "T", "G", "I", "Q",
]

# "A-101", "A101", "A0.1", "M-201.1", "AD101" — a leading discipline letter
# block, optional separator, then a numeric sheet designator.
SHEET_NUMBER_RE = re.compile(
    r"\b([A-Z]{1,2})[-\s]?(\d{1,4}(?:\.\d{1,2})?)\b"
)

# Common title-block boilerplate to exclude when guessing the sheet title
# from OCR'd lines — these regularly out-rank the real title by position
# but aren't it.
_TITLE_EXCLUDE_RE = re.compile(
    r"scale|date|drawn by|checked|revision|project\s*(no|name)?|sheet\s*(\d|number|title)|"
    r"of\s+\d+$|^\s*\d+[/\-]\d+[/\-]\d+\s*$",
    re.IGNORECASE,
)


def title_block_available() -> bool:
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def crop_title_block(img_bgr, region: str = "bottom-right"):
    """
    Title blocks sit in a standard corner on architectural sheets — default
    to bottom-right (the AIA/most common convention). Crops a generous
    fraction of the sheet rather than a tight guess, since OCR accuracy
    matters more than speed here and this only runs once per uploaded page.
    """
    h, w = img_bgr.shape[:2]
    if region == "bottom-right":
        return img_bgr[int(h * 0.75):h, int(w * 0.65):w]
    if region == "bottom-strip":
        return img_bgr[int(h * 0.85):h, 0:w]
    return img_bgr


def _ocr_lines(img_bgr) -> list:
    import cv2
    import pytesseract

    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    # Title blocks are small, dense text — a fixed-size upscale measurably
    # helps tesseract the same way it helps on any small-print scan.
    scale = 2
    resized = cv2.resize(gray, (gray.shape[1] * scale, gray.shape[0] * scale), interpolation=cv2.INTER_CUBIC)
    text = pytesseract.image_to_string(resized)
    return [line.strip() for line in text.splitlines() if line.strip()]


def parse_title_block(lines: list) -> dict:
    """
    Pulls {sheet_number, discipline, sheet_title} out of OCR'd title-block
    lines. Pure function (no OCR calls) so the regex logic is testable
    independent of the OCR engine.
    """
    sheet_number = None
    discipline = None
    for line in lines:
        m = SHEET_NUMBER_RE.search(line.upper())
        if not m:
            continue
        letters, digits = m.group(1), m.group(2)
        # Prefer a two-letter discipline match (AD/AS/FP) over a one-letter
        # prefix of the same string, e.g. "AD101" is AD-101, not A-D101.
        candidate_discipline = letters if letters in DISCIPLINE_CODES else letters[0]
        if candidate_discipline not in DISCIPLINE_CODES:
            continue
        sheet_number = f"{letters}-{digits}"
        discipline = candidate_discipline
        break

    sheet_title = None
    best_len = 0
    for line in lines:
        if _TITLE_EXCLUDE_RE.search(line):
            continue
        if sheet_number and sheet_number.replace("-", "") in line.upper().replace("-", "").replace(" ", ""):
            continue
        # Longest remaining alphabetic-majority line is the best sheet-title
        # guess — title-block text is usually the most prominent line after
        # the sheet number itself (e.g. "FLOOR PLAN - LEVEL 2").
        letters_count = sum(c.isalpha() for c in line)
        if letters_count > best_len and letters_count >= 4:
            best_len = letters_count
            sheet_title = line.strip()

    return {"sheet_number": sheet_number, "discipline": discipline, "sheet_title": sheet_title}


def identify_sheet(img_bgr, page_index: int = 0) -> dict:
    """
    Best-effort per-page identity for plan-set ingestion
    (routes/upload_routes.py's ingest_plan_set()). Always returns a usable
    dict — sheet_title falls back to a numbered placeholder ("Page N") when
    OCR is unavailable or found nothing, never left blank, but
    sheet_number/discipline stay None rather than guessed.
    """
    fallback = {"sheet_number": None, "discipline": None, "sheet_title": f"Page {page_index + 1}"}
    if not title_block_available():
        return fallback

    try:
        crop = crop_title_block(img_bgr)
        lines = _ocr_lines(crop)
        parsed = parse_title_block(lines)
        if not parsed["sheet_title"]:
            parsed["sheet_title"] = fallback["sheet_title"]
        return parsed
    except Exception:
        return fallback
