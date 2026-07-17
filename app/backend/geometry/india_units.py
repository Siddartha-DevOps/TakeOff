"""
India localization for the measurement engine: metric units + IS 1200 rules.

Togal measures to US/AIA conventions in imperial units. Indian construction
tenders are measured to **IS 1200 (Method of measurement of building and civil
engineering works)** in **metric** units — m² for plaster/tiling, m³ for
concrete/brickwork, running metres for linear items. This module converts the
exact vector-geometry output (which is imperial-feet, see ``units.py``) into the
metric quantities an Indian BOQ needs, and applies the IS 1200 measurement rules
that differ materially from AIA — chiefly the deduction rules for openings.

Everything here is derived from exact geometry, so numbers are not predictions.
Correctness-critical: unit-tested in ``tests/test_india_units.py``.

References:
  - IS 1200 (Part 1) — earthwork; (Part 12) — plastering & pointing (deductions);
    (Part 3/5) — concrete/brickwork (measured by volume).
  - The plastering deduction thresholds below follow IS 1200 (Part 12).
"""

from __future__ import annotations

from .units import points_to_feet, sqpoints_to_sqfeet

# ── Exact metric/imperial conversion factors ────────────────────────────────
METERS_PER_FOOT: float = 0.3048            # exact by definition
FEET_PER_METER: float = 1.0 / METERS_PER_FOOT
SQM_PER_SQFT: float = METERS_PER_FOOT ** 2  # 0.09290304, exact
SQFT_PER_SQM: float = 1.0 / SQM_PER_SQFT


# ── Scalar conversions ──────────────────────────────────────────────────────
def feet_to_meters(feet: float) -> float:
    return feet * METERS_PER_FOOT


def meters_to_feet(meters: float) -> float:
    return meters * FEET_PER_METER


def sqft_to_sqm(sqft: float) -> float:
    return sqft * SQM_PER_SQFT


def sqm_to_sqft(sqm: float) -> float:
    return sqm * SQFT_PER_SQM


# ── Direct PDF-geometry → metric (no imperial round-trip loss) ───────────────
def points_to_meters(points: float, scale_ratio: float) -> float:
    """Convert a length in PDF points to real-world metres."""
    return feet_to_meters(points_to_feet(points, scale_ratio))


def sqpoints_to_sqmeters(area_points: float, scale_ratio: float) -> float:
    """Convert an area in square PDF points to real-world square metres."""
    return sqft_to_sqm(sqpoints_to_sqfeet(area_points, scale_ratio))


# ── IS 1200 measurement rules ───────────────────────────────────────────────
#: IS 1200 (Part 12): openings up to this area are NOT deducted from plaster,
#: and no addition is made for their jambs/soffits/sills. Above it, the opening
#: is deducted (per plastered face).
IS1200_PLASTER_NO_DEDUCTION_SQM: float = 0.5


def is1200_plaster_net_area(
    gross_wall_area_sqm: float,
    openings_sqm: list[float] | None = None,
    no_deduction_threshold_sqm: float = IS1200_PLASTER_NO_DEDUCTION_SQM,
) -> float:
    """Net plaster area for one wall face under IS 1200 (Part 12).

    Rule applied: an opening whose area is <= ``no_deduction_threshold_sqm``
    (default 0.5 m²) is not deducted (and no jamb/soffit is added); a larger
    opening is deducted at its full area for that face. This is the common
    tool/BOQ default. Reveal/jamb additions for larger openings are handled
    separately when detailed jamb geometry is available.

    Args:
        gross_wall_area_sqm: Gross plastered face area (m²).
        openings_sqm: Per-opening areas on that face (m²).
    Returns:
        Net plaster area (m²), never negative.
    """
    if gross_wall_area_sqm < 0:
        raise ValueError("gross_wall_area_sqm must be non-negative")
    deductible = sum(
        a for a in (openings_sqm or []) if a > no_deduction_threshold_sqm
    )
    return max(0.0, gross_wall_area_sqm - deductible)


def concrete_volume_cum(area_sqm: float, thickness_m: float) -> float:
    """Concrete/screed volume (m³) = plan area × thickness. IS 1200 (Part 3)."""
    if area_sqm < 0 or thickness_m < 0:
        raise ValueError("area and thickness must be non-negative")
    return area_sqm * thickness_m


def brickwork_volume_cum(
    wall_length_m: float,
    wall_height_m: float,
    wall_thickness_m: float,
    openings_volume_cum: float = 0.0,
) -> float:
    """Net brickwork/masonry volume (m³) under IS 1200 (Part 5/8).

    Gross wall volume (L×H×T) minus the volume occupied by openings. Openings
    are deducted at full volume (masonry is measured net of all openings,
    unlike the plaster small-opening exemption).
    """
    if min(wall_length_m, wall_height_m, wall_thickness_m) < 0:
        raise ValueError("wall dimensions must be non-negative")
    gross = wall_length_m * wall_height_m * wall_thickness_m
    return max(0.0, gross - max(0.0, openings_volume_cum))


# ── measure_result (imperial) → Indian metric quantities ────────────────────
#: Default assumed clear wall height (m) until ceilings are measured. ~9 ft.
DEFAULT_WALL_HEIGHT_M: float = feet_to_meters(9.0)


def india_quantities(
    measure_result: dict,
    wall_height_m: float = DEFAULT_WALL_HEIGHT_M,
) -> list[dict]:
    """Metric, IS 1200-flavoured quantity rows for an Indian BOQ.

    Mirrors ``quantities.vector_quantities`` but emits metric units the DSR/SOR
    rate lookup expects: floor/ceiling area in m², wall plaster in m² (both
    faces), wall length in running metres, space count in nos.

    ``measure_result`` is the imperial output of the vector geometry engine
    (``summary.totalArea`` in sqft, ``summary.walls_lf`` in linear ft).
    """
    summary = measure_result.get("summary", {})
    total_area_sqm = round(sqft_to_sqm(float(summary.get("totalArea", 0.0))), 3)
    walls_m = round(feet_to_meters(float(summary.get("walls_lf", 0.0))), 3)
    n_rooms = int(summary.get("rooms", 0))

    rows: list[dict] = []

    if total_area_sqm > 0:
        rows.append({"trade": "Areas", "item": "Floor area (net)", "quantity": total_area_sqm, "unit": "sqm"})
        rows.append({"trade": "Ceiling", "item": "Ceiling area", "quantity": total_area_sqm, "unit": "sqm"})

    if walls_m > 0:
        # Plaster both faces; IS 1200 net deductions apply once openings are known.
        plaster_sqm = round(walls_m * wall_height_m * 2, 3)
        rows.append({"trade": "Masonry", "item": "Wall length", "quantity": walls_m, "unit": "rmt"})
        rows.append({
            "trade": "Finishing",
            "item": f"Cement plaster (both faces, {wall_height_m:.2f} m ht)",
            "quantity": plaster_sqm,
            "unit": "sqm",
        })

    if n_rooms > 0:
        rows.append({"trade": "Counts", "item": "Spaces", "quantity": n_rooms, "unit": "nos"})

    return rows
