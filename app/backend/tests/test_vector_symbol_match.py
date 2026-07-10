"""Vector symbol-matching tests against synthetic, known-count PDFs.

Doors are drawn as leaf-line + swing-arc, windows as thin rectangles, fixtures
as ovals. The engine must recover the exact counts, cluster identical repeats,
filter structural walls, and emit persistence-ready geometry.
"""

import fitz
import pytest

from geometry.vector_symbol_match import (
    classify_candidate,
    cluster_symbols,
    filter_candidates,
    match_symbols,
    parse_symbol_candidates,
    symbols_to_persistence,
    _page_diag,
)

N_DOORS, N_WINDOWS, N_FIXTURES = 3, 5, 2


@pytest.fixture
def plan_pdf(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=1000, height=800)

    for i in range(N_DOORS):  # door = leaf line + swing arc
        x, y = 100 + i * 120, 120
        sh = page.new_shape()
        sh.draw_line((x, y), (x + 40, y))
        sh.draw_bezier((x + 40, y), (x + 55, y + 15), (x + 55, y + 25), (x + 40, y + 40))
        sh.finish(color=(0, 0, 0), width=1)
        sh.commit()

    for i in range(N_WINDOWS):  # window = thin rectangle
        x, y = 100 + i * 120, 300
        sh = page.new_shape()
        sh.draw_rect(fitz.Rect(x, y, x + 60, y + 8))
        sh.finish(color=(0, 0, 0), width=1)
        sh.commit()

    for i in range(N_FIXTURES):  # fixture = oval (toilet)
        x, y = 150 + i * 200, 500
        sh = page.new_shape()
        sh.draw_oval(fitz.Rect(x, y, x + 30, y + 40))
        sh.finish(color=(0, 0, 0), width=1)
        sh.commit()

    # Structural walls — must be filtered out, not counted.
    for a, b in [((50, 50), (950, 50)), ((50, 50), (50, 750))]:
        sh = page.new_shape()
        sh.draw_line(a, b)
        sh.finish(color=(0, 0, 0), width=2)
        sh.commit()

    p = tmp_path / "plan.pdf"
    doc.save(str(p))
    doc.close()
    return p


def test_counts_per_type_are_exact(plan_pdf):
    result = match_symbols(plan_pdf)
    counts = result["symbol_counts"]
    assert counts.get("door") == N_DOORS
    assert counts.get("window") == N_WINDOWS
    assert counts.get("fixture") == N_FIXTURES
    assert result["total_symbols"] == N_DOORS + N_WINDOWS + N_FIXTURES


def test_walls_are_filtered_out(plan_pdf):
    raw = parse_symbol_candidates(plan_pdf)
    _, _, diag = _page_diag(plan_pdf, 0)
    kept = filter_candidates(raw, diag)
    # 10 symbol candidates kept; the 2 long walls dropped.
    assert len(kept) == N_DOORS + N_WINDOWS + N_FIXTURES


def test_identical_symbols_cluster_together(plan_pdf):
    raw = parse_symbol_candidates(plan_pdf)
    _, _, diag = _page_diag(plan_pdf, 0)
    clusters = cluster_symbols(filter_candidates(raw, diag))
    # Three distinct symbol shapes -> three clusters of the right sizes.
    sizes = sorted(len(c) for c in clusters)
    assert sizes == sorted([N_DOORS, N_WINDOWS, N_FIXTURES])


def test_groups_carry_geometry_for_overlay(plan_pdf):
    result = match_symbols(plan_pdf)
    assert len(result["groups"]) == 3
    for g in result["groups"]:
        assert g["count"] == len(g["instances"])
        for inst in g["instances"]:
            assert inst["geojson"]["type"] == "Polygon"
            assert len(inst["bbox"]) == 4


def test_persistence_records_are_first_class_detections(plan_pdf):
    result = match_symbols(plan_pdf)
    records = symbols_to_persistence(result)
    assert len(records) == N_DOORS + N_WINDOWS + N_FIXTURES
    for rec in records:
        assert rec["detection"]["source"] == "vector"
        assert rec["detection"]["geom_ewkt"].startswith("SRID=0;")
        assert rec["symbol_type"] in {"door", "window", "fixture", "symbol"}


def test_geometric_hash_matches_within_cluster(plan_pdf):
    raw = parse_symbol_candidates(plan_pdf)
    _, _, diag = _page_diag(plan_pdf, 0)
    kept = filter_candidates(raw, diag)
    doors = [c for c in kept if classify_candidate(c) == "door"]
    hashes = {c.geometric_hash() for c in doors}
    assert len(hashes) == 1  # identical doors -> identical hash


def test_empty_pdf_yields_no_symbols(tmp_path):
    doc = fitz.open()
    doc.new_page(width=600, height=400)
    p = tmp_path / "blank.pdf"
    doc.save(str(p))
    doc.close()
    result = match_symbols(p)
    assert result["total_symbols"] == 0
    assert result["symbol_counts"] == {}
