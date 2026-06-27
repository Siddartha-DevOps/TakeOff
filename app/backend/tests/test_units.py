"""Exact unit-conversion tests — the accuracy contract for vector geometry."""

import pytest

from geometry.units import points_to_feet, points_to_real_inches, sqpoints_to_sqfeet


def test_eighth_inch_scale_is_exact():
    # 72 pt = 1 paper inch. At 1/8"=1'-0" (ratio 96), 1 paper inch = 8 ft.
    assert points_to_feet(72, 96) == pytest.approx(8.0)
    assert points_to_real_inches(72, 96) == pytest.approx(96.0)


def test_quarter_inch_scale_is_exact():
    # 1/4"=1'-0" -> ratio 48 -> 1 paper inch = 4 ft.
    assert points_to_feet(72, 48) == pytest.approx(4.0)


def test_area_scales_with_square_of_linear_factor():
    # 1 square paper inch (72x72 pt) at ratio 96 -> (8 ft)^2 = 64 sqft.
    assert sqpoints_to_sqfeet(72 * 72, 96) == pytest.approx(64.0)


def test_area_uses_magnitude_of_signed_area():
    assert sqpoints_to_sqfeet(-(72 * 72), 96) == pytest.approx(64.0)


def test_non_positive_scale_rejected():
    with pytest.raises(ValueError):
        points_to_feet(72, 0)
    with pytest.raises(ValueError):
        points_to_feet(72, -5)
