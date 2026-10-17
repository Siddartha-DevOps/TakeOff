"""Real API app with only the external ML predictor replaced deterministically."""

import numpy as np

import server
from ai.inference import MaskRCNNInference


def _predict_room(image: np.ndarray) -> dict:
    height, width = image.shape[:2]
    mask = np.zeros((1, 1, height, width), dtype=np.float32)
    x1, x2 = max(2, width // 6), max(8, width * 5 // 6)
    y1, y2 = max(2, height // 6), max(8, height * 5 // 6)
    mask[0, 0, y1:y2, x1:x2] = 1.0
    mask[0, 0, y1 : y1 + max(2, (y2 - y1) // 3), x1 : x1 + max(2, (x2 - x1) // 3)] = 0.0
    hx1, hx2 = width * 9 // 20, width * 11 // 20
    hy1, hy2 = height * 9 // 20, height * 11 // 20
    mask[0, 0, hy1:hy2, hx1:hx2] = 0.0
    return {
        "boxes": np.array([[x1, y1, x2 - 1, y2 - 1]], dtype=np.float32),
        "labels": np.array([4], dtype=np.int64),
        "scores": np.array([0.99], dtype=np.float32),
        "masks": mask,
    }


server.ai_engine = MaskRCNNInference(
    "deterministic-e2e-fixture.pt",
    device="cpu",
    predictor=_predict_room,
    model_version="maskrcnn-deterministic-e2e",
)
app = server.app
