from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from ml.prediction import GeometryType, Prediction


BASE = dict(
    prediction_id="p1", model_id="rooms", model_version="v1", dataset_version="d1",
    drawing_id=1, page_id=2, **{"class": "bedroom"}, confidence=0.9,
    created_at=datetime.now(timezone.utc),
)


@pytest.mark.parametrize(("kind", "geometry"), [
    (GeometryType.POINT, [1, 2]),
    (GeometryType.BOUNDING_BOX, [0, 0, 10, 20]),
    (GeometryType.LINESTRING, [[0, 0], [1, 1]]),
    (GeometryType.POLYGON, [[0, 0], [1, 0], [1, 1], [0, 0]]),
])
def test_supported_geometry_types(kind, geometry):
    prediction = Prediction(**BASE, geometry_type=kind, geometry=geometry)
    assert prediction.model_dump(by_alias=True)["class"] == "bedroom"


@pytest.mark.parametrize(("kind", "geometry"), [
    (GeometryType.BOUNDING_BOX, [0, 0, 0, 1]),
    (GeometryType.LINESTRING, [[0, 0]]),
    (GeometryType.POLYGON, [[0, 0], [1, 0], [1, 1]]),
])
def test_invalid_geometry_is_rejected(kind, geometry):
    with pytest.raises(ValidationError):
        Prediction(**BASE, geometry_type=kind, geometry=geometry)


def test_confidence_and_provenance_are_required():
    with pytest.raises(ValidationError):
        Prediction(**{key: value for key, value in BASE.items() if key != "model_version"},
                   geometry_type="POINT", geometry=[0, 0])
    with pytest.raises(ValidationError):
        Prediction(**{**BASE, "confidence": 1.1}, geometry_type="POINT", geometry=[0, 0])
