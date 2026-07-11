"""PDF-point -> 300-DPI raster-pixel conversion for persistence."""

import pytest

from geometry.coords import PX_PER_POINT, REFERENCE_DPI, bbox_to_pixels, points_to_pixels, ring_to_pixels


def test_reference_dpi_and_factor():
    assert REFERENCE_DPI == 300.0
    assert PX_PER_POINT == pytest.approx(300 / 72)


def test_points_to_pixels_scales_by_300_over_72():
    # 72 pt = 1 inch = 300 px at 300 DPI.
    assert points_to_pixels(72) == pytest.approx(300.0)
    assert points_to_pixels(144) == pytest.approx(600.0)


def test_bbox_converts_all_four_corners():
    assert bbox_to_pixels([0, 0, 72, 144]) == pytest.approx([0, 0, 300, 600])


def test_ring_converts_each_vertex():
    ring = [[0, 0], [72, 0], [72, 72]]
    got = ring_to_pixels(ring)
    flat = [c for vertex in got for c in vertex]
    assert flat == pytest.approx([0, 0, 300, 0, 300, 300])


def test_area_ratio_is_factor_squared():
    # A 72x72 pt square (1 in^2) -> 300x300 px; pixel area = (300/72)^2 x point area.
    box_px = bbox_to_pixels([0, 0, 72, 72])
    w = box_px[2] - box_px[0]
    assert (w * w) == pytest.approx((72 * 72) * PX_PER_POINT ** 2)
