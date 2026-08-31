from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from scale_validation import is_scale_confirmed, require_confirmed_scale


@pytest.mark.parametrize("source", ["manual", "ocr"])
def test_confirmed_sources_return_persisted_ratio(source):
    drawing = SimpleNamespace(id=7, scale_ratio=96.0, scale_source=source)
    assert is_scale_confirmed(drawing)
    assert require_confirmed_scale(drawing) == 96.0


@pytest.mark.parametrize(
    ("ratio", "source"),
    [(None, None), (96.0, None), (96.0, "default"), (0, "manual"), (-1, "ocr")],
)
def test_unconfirmed_or_invalid_scale_is_rejected(ratio, source):
    drawing = SimpleNamespace(id=9, scale_ratio=ratio, scale_source=source)
    assert not is_scale_confirmed(drawing)
    with pytest.raises(HTTPException) as exc:
        require_confirmed_scale(drawing)
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "scale_confirmation_required"
    assert exc.value.detail["drawing_id"] == 9


def test_detected_but_unconfirmed_scale_is_rejected_even_with_high_confidence():
    drawing = SimpleNamespace(
        id=10, scale_ratio=100.0, scale_source="ocr",
        scale_confidence=0.99, scale_requires_confirmation=True, file_type="PDF",
    )
    assert not is_scale_confirmed(drawing)
    with pytest.raises(HTTPException):
        require_confirmed_scale(drawing)
