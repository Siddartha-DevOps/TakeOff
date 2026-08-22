from types import SimpleNamespace

from ai.space.result_schema import serialize_result


class FakeTensor:
    def __init__(self, value):
        self.value = value

    def detach(self):
        return self

    def cpu(self):
        return self

    def tolist(self):
        return self.value


def test_serializes_boxes_masks_and_dimensions():
    result = SimpleNamespace(
        orig_shape=(768, 1024),
        names={2: "bathroom"},
        boxes=SimpleNamespace(
            cls=FakeTensor([2]),
            conf=FakeTensor([0.87654321]),
            xyxy=FakeTensor([[10.1234, 20.5678, 300.0, 400.0]]),
        ),
        masks=SimpleNamespace(
            xyn=[FakeTensor([[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]])]
        ),
    )

    payload = serialize_result(result)

    assert payload["image_width"] == 1024
    assert payload["image_height"] == 768
    assert payload["detections"] == [{
        "class_id": 2,
        "class_name": "bathroom",
        "confidence": 0.876543,
        "bbox_xyxy": [10.123, 20.568, 300.0, 400.0],
        "polygon_normalized": [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]],
    }]


def test_handles_result_without_boxes():
    assert serialize_result(SimpleNamespace(boxes=None)) == {
        "image_width": 0,
        "image_height": 0,
        "detections": [],
    }
