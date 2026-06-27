"""Vector-PDF engine tests against synthetic, known-dimension PDFs.

The whole pitch of the vector engine is exactness, so the assertions are tight:
areas/lengths must match the drawn geometry to a fraction of a unit, because no
rasterization or detection sits between the file and the measurement.
"""

import fitz
import pytest

from geometry import extract_page_geometry, is_vector_pdf_page, measure_pdf
from geometry.vector_pdf import MIN_VECTOR_SEGMENTS

# 1/8" = 1'-0"  ->  ratio 96  ->  1 paper inch (72 pt) = 8 ft.
SCALE_RATIO = 96.0

# Each room: 144 x 72 pt = 2 x 1 paper inch = 16 x 8 ft = 128 sqft.
ROOM_W_PT = 144.0
ROOM_H_PT = 72.0
EXPECTED_ROOM_SQFT = 128.0


def _make_vector_pdf(path, n_rooms=4):
    """A page with `n_rooms` separated rectangles (real vector linework)."""
    doc = fitz.open()
    page = doc.new_page(width=1200, height=800)
    for i in range(n_rooms):
        x0 = 50 + (i % 2) * (ROOM_W_PT + 40)
        y0 = 50 + (i // 2) * (ROOM_H_PT + 40)
        page.draw_rect(
            fitz.Rect(x0, y0, x0 + ROOM_W_PT, y0 + ROOM_H_PT),
            color=(0, 0, 0),
            width=1,
        )
    doc.save(str(path))
    doc.close()


def _make_raster_pdf(path):
    """A page with no vector linework (stands in for a scanned sheet)."""
    doc = fitz.open()
    page = doc.new_page(width=1200, height=800)
    page.insert_text((100, 100), "SCANNED PLAN")
    doc.save(str(path))
    doc.close()


@pytest.fixture
def vector_pdf(tmp_path):
    p = tmp_path / "vector.pdf"
    _make_vector_pdf(p)
    return p


def test_detects_vector_page(vector_pdf):
    vp = extract_page_geometry(vector_pdf)
    assert vp.is_vector
    assert len(vp.segments) >= MIN_VECTOR_SEGMENTS
    assert is_vector_pdf_page(vector_pdf)


def test_room_areas_are_exact(vector_pdf):
    result = measure_pdf(vector_pdf, SCALE_RATIO)
    assert result is not None
    assert result["method"] == "vector"
    assert result["summary"]["rooms"] == 4

    for room in result["rooms"]:
        assert room["area"] == pytest.approx(EXPECTED_ROOM_SQFT, abs=0.5)

    assert result["summary"]["totalArea"] == pytest.approx(4 * EXPECTED_ROOM_SQFT, abs=2.0)


def test_wall_linear_feet_is_exact(vector_pdf):
    vp = extract_page_geometry(vector_pdf)
    # 4 rooms x perimeter(2*(144+72)=432 pt) = 1728 pt -> 192 ft at ratio 96.
    assert vp.wall_linear_feet(SCALE_RATIO) == pytest.approx(192.0, abs=0.5)


def test_room_geometry_is_present_for_persistence(vector_pdf):
    result = measure_pdf(vector_pdf, SCALE_RATIO)
    room = result["rooms"][0]
    assert room["geometry"] is not None
    assert room["geometry"].area == pytest.approx(ROOM_W_PT * ROOM_H_PT, abs=1.0)


def test_raster_page_returns_none(tmp_path):
    p = tmp_path / "raster.pdf"
    _make_raster_pdf(p)
    assert not is_vector_pdf_page(p)
    assert measure_pdf(p, SCALE_RATIO) is None
