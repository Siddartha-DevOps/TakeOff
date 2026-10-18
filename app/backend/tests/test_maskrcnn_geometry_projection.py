import models
from ai.inference.engine import TakeoffAnalysis
from detection_geometry import _room_to_wkt_polygon, persist_detection_geometries
from routes.takeoff_routes import _normalize_pdf_analysis_to_plan_space


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


def test_pdf_mask_coordinates_are_normalized_from_actual_raster_dimensions(tmp_path):
    import fitz
    from PIL import Image

    pdf_path = tmp_path / "plan.pdf"
    raster_path = tmp_path / "plan.png"
    with fitz.open() as document:
        document.new_page(width=300, height=200)
        document.save(pdf_path)
    Image.new("RGB", (1250, 800), "white").save(raster_path)
    room = {
        "id": "room-1",
        "label": "living",
        "bbox": [125, 80, 1125, 720],
        "polygon": [[125, 80], [1125, 80], [1125, 720], [125, 720]],
        "holes": [[[500, 320], [750, 320], [750, 480], [500, 480]]],
        "area": 600000,
    }
    analysis = TakeoffAnalysis(
        drawing_id=1,
        processing_time_ms=1,
        ai_model_version="fixture",
        rooms=[room],
        doors=[],
        windows=[],
        walls=[],
        balconies=[],
        summary={},
        quantities=[],
        confidence_avg=0.9,
    )

    _normalize_pdf_analysis_to_plan_space(analysis, str(pdf_path), 0, str(raster_path))

    assert room["bbox"] == [30.0, 20.0, 270.0, 180.0]
    assert room["polygon"][2] == [270.0, 180.0]
    assert room["holes"][0][0] == [120.0, 80.0]
    assert room["area"] == 36000.0
