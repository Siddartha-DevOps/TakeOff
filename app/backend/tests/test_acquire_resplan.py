"""Tests for the official ResPlan -> TakeOff spaces-v1 converter."""

import json
import pickle

import pytest

shapely = pytest.importorskip("shapely")
from shapely.geometry import MultiPolygon, Polygon

from ml.datasets.acquire_resplan import (
    RestrictedResPlanUnpickler,
    _normalized_ring,
    convert_resplan_dataset,
    render_plan,
    semantic_fingerprint,
)


def _plan(plan_id, *, flip=False):
    left = Polygon([(0, 0), (5, 0), (5, 5), (0, 5)])
    right = Polygon([(5, 0), (10, 0), (10, 5), (5, 5)])
    if flip:
        left, right = right, left
    return {
        "id": plan_id,
        "inner": Polygon([(0, 0), (10, 0), (10, 5), (0, 5)]),
        "wall": MultiPolygon([Polygon([(0, 0), (10, 0), (10, .2), (0, .2)])]),
        "door": MultiPolygon([]), "window": MultiPolygon([]),
        "front_door": Polygon(), "living": left, "bedroom": right,
        "bathroom": MultiPolygon([]), "kitchen": MultiPolygon([]),
        "balcony": MultiPolygon([]), "stair": MultiPolygon([]), "storage": MultiPolygon([]),
    }


def _source(tmp_path, plans, splits):
    pickle_path = tmp_path / "ResPlan.pkl"
    split_path = tmp_path / "split.json"
    pickle_path.write_bytes(pickle.dumps(plans, protocol=4))
    split_path.write_text(json.dumps(splits))
    return pickle_path, split_path


def test_render_plan_produces_monochrome_image_and_yolo_polygons():
    image, lines = render_plan(_plan(1), canvas=256)
    assert image.mode == "L" and image.size == (256, 256)
    assert len(lines) == 2
    assert {int(line.split()[0]) for line in lines} == {0, 1}
    assert all(0 <= float(value) <= 1 for line in lines for value in line.split()[1:])


def test_quantization_drops_collapsed_polygon():
    assert _normalized_ring([(1, 1), (1.000001, 1), (1, 1.000001)], 768) == []


def test_semantic_fingerprint_is_reflection_invariant():
    assert semantic_fingerprint(_plan(1)) == semantic_fingerprint(_plan(2, flip=True))


def test_converter_preserves_splits_and_writes_contract(tmp_path):
    plans = [_plan(1), _plan(2, flip=True), _plan(3)]
    source = _source(tmp_path, plans, {"train": [1], "val": [2], "test": [3], "augmented": []})
    out = tmp_path / "out"
    summary = convert_resplan_dataset(*source, out, canvas=128)

    assert summary["train"] == 1
    assert summary["dropped_cross_split_layout"] == 2
    assert (out / "data.yaml").is_file()
    assert (out / "groups.json").is_file()
    assert json.loads((out / "source_metadata.json").read_text())["license"] == "CC BY 4.0"


def test_restricted_unpickler_rejects_unknown_global(tmp_path):
    path = tmp_path / "bad.pkl"
    path.write_bytes(pickle.dumps(len))
    with path.open("rb") as handle, pytest.raises(pickle.UnpicklingError, match="forbidden"):
        RestrictedResPlanUnpickler(handle).load()
