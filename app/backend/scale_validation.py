"""Shared safety gate for any operation that emits measured quantities."""

from fastapi import HTTPException, status


CONFIRMED_SCALE_SOURCES = frozenset({"manual", "ocr"})


def is_scale_confirmed(drawing) -> bool:
    """A scale is trusted only after a user calibrates or accepts OCR."""
    ratio = getattr(drawing, "scale_ratio", None)
    source = getattr(drawing, "scale_source", None)
    requires_confirmation = getattr(drawing, "scale_requires_confirmation", None)
    if requires_confirmation is True:
        return False
    if not (ratio and ratio > 0 and source in CONFIRMED_SCALE_SOURCES):
        return False
    file_type = str(getattr(drawing, "file_type", "") or "").upper()
    if file_type and file_type != "PDF":
        # Historical/manual raster calibration is explicitly defined against
        # 300 plan units/inch. Automatic raster scale needs recorded source DPI.
        dpi = getattr(drawing, "scale_dpi", None)
        if dpi is None and source != "manual":
            return False
    return True


def require_confirmed_scale(drawing) -> float:
    """Return the persisted ratio or reject measurement/export safely."""
    if not is_scale_confirmed(drawing):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "scale_confirmation_required",
                "message": "Confirm this drawing's scale before running takeoff or exporting measured quantities.",
                "drawing_id": getattr(drawing, "id", None),
            },
        )
    return float(drawing.scale_ratio)
