from pathlib import Path

import pytest

fitz = pytest.importorskip("fitz")

from ocr_index import extract_text_blocks, _kind


def test_extracts_native_pdf_text_without_ocr(tmp_path: Path):
    path = tmp_path / "A101.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "FIRE EXTINGUISHER CABINET TYPE A")
    document.save(path)
    document.close()

    blocks = extract_text_blocks(str(path), 0)
    assert any("FIRE EXTINGUISHER" in block["text"] for block in blocks)
    assert all(len(block["bbox"]) == 4 for block in blocks)


def test_specification_classification_uses_filename_or_text_density():
    assert _kind("project-specifications.pdf", "short") == "specification"
    assert _kind("A101.pdf", "short") == "drawing"
    assert _kind("book.pdf", "x" * 5001) == "specification"
