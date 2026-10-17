import models
from detection_geometry import _room_to_wkt_polygon, persist_detection_geometries


def test_room_projection_uses_mask_polygon_holes_not_bbox():
    geom = _room_to_wkt_polygon(
        {
            "bbox": [0, 0, 20, 20],
            "polygon": [[1, 1], [19, 1], [19, 19], [1, 19]],
            "holes": [[[8, 8], [12, 8], [12, 12], [8, 12]]],
        }
    )
    assert (
        geom.data
        == "POLYGON((1 1, 19 1, 19 19, 1 19, 1 1), (8 8, 12 8, 12 12, 8 12, 8 8))"
    )


def test_room_projection_retains_bbox_compatibility():
    geom = _room_to_wkt_polygon({"bbox": [1, 2, 3, 4]})
    assert geom.data == "POLYGON((1 2, 3 2, 3 4, 1 4, 1 2))"


class _Query:
    def filter(self, *_args):
        return self

    def all(self):
        return []

    def delete(self, **_kwargs):
        return 0


class _Db:
    def __init__(self):
        self.added = []

    def query(self, _model):
        return _Query()

    def add(self, value):
        self.added.append(value)

    def flush(self):
        return None

    def commit(self):
        return None


def test_mask_room_persists_calibrated_area_and_mask_geometry():
    db = _Db()
    created = persist_detection_geometries(
        db,
        3,
        7,
        {
            "rooms": [
                {
                    "id": "room-1",
                    "label": "living",
                    "bbox": [0, 0, 20, 20],
                    "polygon": [[1, 1], [19, 1], [19, 19], [1, 19]],
                    "holes": [[[8, 8], [12, 8], [12, 12], [8, 12]]],
                    "area": 308,
                    "area_sqft": 42.5,
                    "confidence": 0.95,
                }
            ]
        },
    )
    assert created == 1
    measurement = next(
        item for item in db.added if isinstance(item, models.Measurement)
    )
    assert measurement.value == 42.5
    assert measurement.unit == "sf"
    assert "), (" in measurement.geom.data
