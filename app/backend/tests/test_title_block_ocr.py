"""Sheet auto-naming tests (ai/title_block_ocr.py) — Togal-parity "auto-naming /
instant labels": pytesseract was declared in the module's own docstring but
never actually added to requirements.txt, so on a real install
title_block_available() was always False and every sheet silently kept its
"Page N" placeholder forever. Fixed by adding pytesseract to
requirements.txt; these tests lock in both the pure parsing logic (no OCR
engine needed) and a real OCR round-trip against a synthetic title block.
"""

import numpy as np
import pytest

from ai.title_block_ocr import (
    identify_sheet,
    parse_title_block,
    title_block_available,
)


def test_parse_title_block_extracts_sheet_number_discipline_title():
    lines = ["A-101", "FLOOR PLAN - LEVEL 2", "SCALE: 1/8=1-0", "DRAWN BY: JS"]
    result = parse_title_block(lines)
    assert result["sheet_number"] == "A-101"
    assert result["discipline"] == "A"
    assert result["sheet_title"] == "FLOOR PLAN - LEVEL 2"


def test_parse_title_block_prefers_two_letter_discipline():
    # "AD101" is AD-101 (existing/demolition), not A-D101.
    lines = ["AD101", "EXISTING CONDITIONS PLAN"]
    result = parse_title_block(lines)
    assert result["sheet_number"] == "AD-101"
    assert result["discipline"] == "AD"


def test_parse_title_block_excludes_boilerplate_from_title():
    lines = ["M-201.1", "SHEET 3 OF 12", "REVISION 2", "MECHANICAL PLAN - ROOF"]
    result = parse_title_block(lines)
    assert result["sheet_number"] == "M-201.1"
    assert result["sheet_title"] == "MECHANICAL PLAN - ROOF"


def test_parse_title_block_no_match_returns_none_not_guess():
    lines = ["SCALE: NTS", "DATE: 01/01/2026"]
    result = parse_title_block(lines)
    assert result["sheet_number"] is None
    assert result["discipline"] is None
    # sheet_title stays None here too -- identify_sheet(), not this pure
    # function, is responsible for the "Page N" placeholder fallback.
    assert result["sheet_title"] is None


def test_identify_sheet_falls_back_to_placeholder_without_tesseract(monkeypatch):
    import ai.title_block_ocr as tbo

    monkeypatch.setattr(tbo, "title_block_available", lambda: False)
    result = identify_sheet(np.zeros((10, 10, 3), dtype=np.uint8), page_index=2)
    assert result == {"sheet_number": None, "discipline": None, "sheet_title": "Page 3"}


@pytest.mark.skipif(not title_block_available(), reason="tesseract-ocr binary/pytesseract not installed")
def test_identify_sheet_real_ocr_round_trip():
    """
    End-to-end: renders an actual title block into an image (matching
    crop_title_block()'s default bottom-right region) and runs real
    tesseract OCR over it -- not just the regex layer above.
    """
    import cv2
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (1000, 800), "white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22)
    except OSError:
        font = ImageFont.load_default()

    # Region is img[0.75h:h, 0.65w:w] = [600:800, 650:1000].
    draw.text((680, 650), "A-101", fill="black", font=font)
    draw.text((680, 690), "FLOOR PLAN - LEVEL 2", fill="black", font=font)
    draw.text((680, 730), "SCALE: 1/8=1-0", fill="black", font=font)
    draw.text((680, 760), "DRAWN BY: JS", fill="black", font=font)

    img_bgr = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    result = identify_sheet(img_bgr, page_index=0)

    assert result["sheet_number"] == "A-101"
    assert result["discipline"] == "A"
    assert result["sheet_title"] == "FLOOR PLAN - LEVEL 2"
