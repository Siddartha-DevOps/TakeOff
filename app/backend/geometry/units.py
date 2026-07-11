"""
Exact unit conversion for the vector-PDF geometry engine.

The whole point of measuring vector geometry is that it is *exact*. PDF user
space is defined in points where 1 point = 1/72 inch, regardless of how (or
whether) the page is ever rasterized. So a length read from the PDF converts to
real-world feet with no DPI assumption and no rounding through a pixel grid.

`scale_ratio` follows the same convention used everywhere else in the codebase
(see ``ai/scale_detection.py``): it is the number of real-world inches per inch
of paper. For ``1/8" = 1'-0"`` one paper inch represents 8 ft = 96 in, so
``scale_ratio == 96``.

Contrast with the raster path (``ai/preprocessing.pixels_to_feet``), which must
divide by an *assumed* scan DPI (300). If the real render DPI differs, every
raster measurement is off by that ratio. The functions here have no such knob.
"""

from __future__ import annotations

#: PDF user-space unit: 1 point = 1/72 inch. This is fixed by the PDF spec.
POINTS_PER_INCH: float = 72.0
INCHES_PER_FOOT: float = 12.0


def points_to_real_inches(points: float, scale_ratio: float) -> float:
    """Convert a length in PDF points to real-world inches.

    paper_inches = points / 72; real_inches = paper_inches * scale_ratio.
    """
    if scale_ratio <= 0:
        raise ValueError(f"scale_ratio must be positive, got {scale_ratio}")
    paper_inches = points / POINTS_PER_INCH
    return paper_inches * scale_ratio


def points_to_feet(points: float, scale_ratio: float) -> float:
    """Convert a length in PDF points to real-world decimal feet."""
    return points_to_real_inches(points, scale_ratio) / INCHES_PER_FOOT


def sqpoints_to_sqfeet(area_points: float, scale_ratio: float) -> float:
    """Convert an area in square PDF points to real-world square feet.

    Area scales with the square of the linear factor, so we compute feet per
    point once and square it. Negative areas (e.g. a signed shoelace result)
    are treated as their magnitude.
    """
    feet_per_point = points_to_feet(1.0, scale_ratio)
    return abs(area_points) * (feet_per_point ** 2)
