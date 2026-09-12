import numpy as np
import fitz

from ai.scale_detection import (
    extract_pdf_scale_candidates,
    parse_scale_candidates,
    parse_scale_from_text,
    run_ocr_for_scale,
    scale_ratio_to_string,
    select_scale_candidate,
)
from ai.title_block_ocr import parse_title_block


def _ocr(text, confidence=0.95, bbox=None):
    return {"text": text, "confidence": confidence, "bbox": bbox}


def test_parses_metric_scales():
    for text, expected in (("SCALE 1:50", 50), ("1 : 100", 100), ("Scale: 1:200", 200)):
        assert parse_scale_from_text([_ocr(text)])["ratio"] == expected


def test_parses_imperial_architectural_scales():
    assert parse_scale_from_text([_ocr('1/8" = 1\'-0"')])["ratio"] == 96
    assert parse_scale_from_text([_ocr('SCALE 1/4" = 1\'-0"')])["ratio"] == 48


def test_title_block_parser_returns_scale_provenance():
    result = parse_title_block(["A-101", "FLOOR PLAN", "SCALE: 1:100"])
    assert result["sheet_number"] == "A-101"
    assert result["scale_candidate"]["ratio"] == 100
    assert result["scale_candidate"]["method"] == "title_block_ocr"


def test_dimension_scale_context_is_useful_without_parsing_plain_dimensions():
    candidates = parse_scale_candidates([_ocr("DIMENSION SCALE 1:20"), _ocr("ROOM 10'-0\"")])
    assert [item["ratio"] for item in candidates] == [20]


def test_conflicting_candidates_are_not_silently_trusted():
    selected = select_scale_candidate(parse_scale_candidates([
        _ocr("SCALE 1:50", 0.99), _ocr("SCALE 1:100", 0.98),
    ]))
    assert selected["conflict"] is True
    assert selected["requires_confirmation"] is True
    assert {item["ratio"] for item in selected["candidates"]} == {50, 100}


def test_invalid_or_unknown_text_has_no_default_scale():
    assert parse_scale_from_text([_ocr("NOT TO SCALE")]) is None
    assert parse_scale_from_text([_ocr("SCALE 1:0")]) is None
    assert parse_scale_from_text([_ocr("SCALE 1:999999")]) is None


def test_missing_ocr_dependency_or_no_text_never_returns_default(monkeypatch):
    # An all-white raster has no safe textual scale. The function may report
    # an unresolved graphic bar on unusual OpenCV versions, but never ratio 96.
    result = run_ocr_for_scale(np.full((100, 100, 3), 255, dtype=np.uint8))
    assert result is None or result.get("ratio") is None


def test_vector_pdf_scale_is_extracted_per_page(tmp_path):
    path = tmp_path / "two-scales.pdf"
    with fitz.open() as document:
        page0 = document.new_page(width=612, height=792)
        page0.insert_text((420, 740), "SCALE 1:50")
        page1 = document.new_page(width=612, height=792)
        page1.insert_text((420, 740), "SCALE 1:100")
        document.save(path)
    first = select_scale_candidate(extract_pdf_scale_candidates(path, 0))
    second = select_scale_candidate(extract_pdf_scale_candidates(path, 1))
    assert first["ratio"] == 50
    assert second["ratio"] == 100
    assert first["method"] == "title_block_pdf_vector"


def test_scale_labels_preserve_metric_ratio_notation():
    assert scale_ratio_to_string(50) == "1:50"
    assert scale_ratio_to_string(100) == "1:100"
