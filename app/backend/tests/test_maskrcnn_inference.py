import numpy as np
import pytest
from PIL import Image

from ai.inference import MaskRCNNInference, maskrcnn_output_to_detections


def _output_with_hole():
    mask = np.zeros((1, 1, 20, 24), dtype=np.float32)
    mask[0, 0, 2:18, 3:21] = 1
    mask[0, 0, 8:12, 9:15] = 0
    return {
        "boxes": np.array([[3, 2, 20, 17]], dtype=np.float32),
        "labels": np.array([4], dtype=np.int64),
        "scores": np.array([0.95], dtype=np.float32),
        "masks": mask,
    }


def test_maskrcnn_output_preserves_polygon_hole_and_taxonomy():
    [room] = maskrcnn_output_to_detections(_output_with_hole())
    assert room["label"] == "living"
    assert room["class_id"] == 4
    assert len(room["polygon"]) >= 4
    assert len(room["holes"]) == 1
    assert room["area"] > 0
    assert room["bbox"] == [3, 2, 21, 18]


def test_maskrcnn_analysis_uses_existing_contract_with_injected_predictor(tmp_path):
    image = tmp_path / "sheet.png"
    Image.new("RGB", (24, 20), "white").save(image)
    engine = MaskRCNNInference(
        str(tmp_path / "not-required.pt"),
        device="cpu",
        predictor=lambda _image: _output_with_hole(),
        model_version="fixture-v1",
    )
    result = engine.analyze(str(image), drawing_id=17)
    assert result.drawing_id == 17
    assert result.ai_model_version == "fixture-v1"
    assert result.summary["rooms"] == 1
    assert result.rooms[0]["holes"]
    assert result.confidence_avg == pytest.approx(0.95)


def test_maskrcnn_converter_rejects_misaligned_output_lengths():
    output = _output_with_hole()
    output["scores"] = np.array([], dtype=np.float32)
    with pytest.raises(ValueError, match="do not reconcile"):
        maskrcnn_output_to_detections(output)
