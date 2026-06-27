"""AUTODETECT primitive tests — exact Area/Line/Count from vector geometry."""

import fitz
import pytest

from geometry import autodetect_from_measure, measure_pdf, vector_quantities

SCALE_RATIO = 96.0  # 1/8"=1'-0"
ROOM_W_PT, ROOM_H_PT = 144.0, 72.0   # 16 x 8 ft = 128 sqft each
EXPECTED_ROOM_SQFT = 128.0


@pytest.fixture
def vector_pdf(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=1200, height=800)
    for i in range(4):
        x0 = 50 + (i % 2) * (ROOM_W_PT + 40)
        y0 = 50 + (i // 2) * (ROOM_H_PT + 40)
        page.draw_rect(fitz.Rect(x0, y0, x0 + ROOM_W_PT, y0 + ROOM_H_PT), color=(0, 0, 0), width=1)
    p = tmp_path / "plan.pdf"
    doc.save(str(p))
    doc.close()
    return p


def test_primitives_are_area_line_count(vector_pdf):
    result = autodetect_from_measure(measure_pdf(vector_pdf, SCALE_RATIO))
    prim = result["primitives"]
    # Area: 4 x 128 = 512 sqft. Line: 192 lf. Count: 4 spaces.
    assert prim["area"] == pytest.approx(512.0, abs=2.0)
    assert prim["line"] == pytest.approx(192.0, abs=0.5)
    assert prim["count"] == 4


def test_area_entries_carry_geometry_for_overlay(vector_pdf):
    measure = measure_pdf(vector_pdf, SCALE_RATIO)
    # Mimic the route: serialize geometry to GeoJSON before building the response.
    from geometry.postgis import to_geojson
    for room in measure["rooms"]:
        room["geojson"] = to_geojson(room.pop("geometry"))

    result = autodetect_from_measure(measure)
    assert len(result["area"]) == 4
    for space in result["area"]:
        assert space["sqft"] == pytest.approx(EXPECTED_ROOM_SQFT, abs=0.5)
        assert space["geojson"]["type"] == "Polygon"


def test_page_dimensions_present_for_overlay(vector_pdf):
    result = autodetect_from_measure(measure_pdf(vector_pdf, SCALE_RATIO))
    assert result["page"]["width_pt"] == pytest.approx(1200, abs=1)
    assert result["page"]["height_pt"] == pytest.approx(800, abs=1)


def test_quantities_include_area_line_count_trades(vector_pdf):
    rows = vector_quantities(measure_pdf(vector_pdf, SCALE_RATIO))
    trades = {r["trade"] for r in rows}
    assert {"Areas", "Walls", "Counts"} <= trades
    wall_lf = next(r for r in rows if r["item"] == "Wall linear feet")
    assert wall_lf["unit"] == "lf"
    assert wall_lf["quantity"] == pytest.approx(192.0, abs=0.5)


def test_empty_measure_yields_no_quantities():
    empty = {"summary": {"totalArea": 0, "walls_lf": 0, "rooms": 0}, "rooms": []}
    assert vector_quantities(empty) == []
    result = autodetect_from_measure(empty)
    assert result["primitives"] == {"area": 0.0, "line": 0.0, "count": 0}
