"""Tests for the golden prediction dumper (stub engine — no torch/GPU)."""

import struct
from dataclasses import dataclass, field

from ml.eval.predict_golden import (
    analysis_to_detections,
    list_split_images,
    predict_split,
)


def _fake_png(path, w, h):
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = b"IHDR" + struct.pack(">II", w, h) + b"\x08\x06\x00\x00\x00"
    path.write_bytes(sig + struct.pack(">I", 13) + ihdr)


@dataclass
class FakeAnalysis:
    rooms: list = field(default_factory=list)
    doors: list = field(default_factory=list)
    windows: list = field(default_factory=list)
    walls: list = field(default_factory=list)
    balconies: list = field(default_factory=list)


class StubEngine:
    """Returns one room + one door for every image (no model needed)."""
    def analyze(self, path, drawing_id):
        return FakeAnalysis(
            rooms=[{"label": "living", "polygon": [[0, 0], [50, 0], [50, 50], [0, 50]], "confidence": 0.9}],
            doors=[{"label": "door", "bbox": [10, 10, 20, 20], "confidence": 0.8}],
        )


def test_list_split_images(tmp_path):
    d = tmp_path / "ds" / "images" / "val"
    d.mkdir(parents=True)
    _fake_png(d / "s1.png", 100, 100)
    _fake_png(d / "s0.png", 100, 100)
    ids = [i for i, _ in list_split_images(tmp_path / "ds")]
    assert ids == ["s0", "s1"]  # sorted


def test_analysis_to_detections_flattens_all_groups():
    a = FakeAnalysis(rooms=[{"label": "living"}], doors=[{"label": "door"}],
                     windows=[{"label": "window"}])
    dets = analysis_to_detections(a)
    assert {d["label"] for d in dets} == {"living", "door", "window"}


def test_predict_split_produces_harness_pred_shape(tmp_path):
    ds = tmp_path / "ds"
    (ds / "images" / "val").mkdir(parents=True)
    _fake_png(ds / "images" / "val" / "s0.png", 100, 100)

    preds = predict_split(StubEngine(), ds, ["living", "bedroom", "door"], split="val")
    assert "s0" in preds
    p = preds["s0"]
    assert len(p["rooms"]) == 1                       # living -> room ring
    assert p["symbols"]["door"][0]["score"] == 0.8    # door -> scored box
    assert p["quantities"]["room_count"] == 1
