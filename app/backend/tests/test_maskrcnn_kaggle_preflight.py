import gzip
import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from ml.training import maskrcnn_kaggle_preflight as preflight


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture_manifest(tmp_path: Path, monkeypatch) -> Path:
    from ml.datasets import adapt_swiss_rooms_maskrcnn_full as adapter

    transform = {"image_size_px": [64, 64], "source_bounds_m": [0, 0, 6, 6], "padding_m": 1, "pixels_per_metre": 8}
    rows = []
    specs = [
        ("train", "hole", "POLYGON ((1 1, 5 1, 5 5, 1 5, 1 1), (2 2, 3 2, 3 3, 2 3, 2 2))"),
        ("val", "positive", "POLYGON ((1 1, 5 1, 5 5, 1 5, 1 1))"),
        ("train", "negative", None),
    ]
    for index, (split, floor_id, geometry) in enumerate(specs, start=1):
        source = tmp_path / "source" / floor_id
        source.mkdir(parents=True)
        Image.new("RGB", (64, 64), "white").save(source / "image.png")
        Image.new("I;16", (64, 64), 0).save(source / "room_instance.png")
        (source / "metadata.json").write_text(json.dumps({"transform": transform}))
        rooms = [] if geometry is None else [{
            "geometry_id": f"room-{index}", "target_family": "spaces", "target_class": "bedroom",
            "target_class_id": 1, "mapping_state": "TRAIN", "excluded": False,
            "geometry_wkt_metric": geometry,
        }]
        with gzip.GzipFile(filename="", mode="wb", fileobj=(source / "supervision.json.gz").open("wb"), mtime=0) as handle:
            handle.write(json.dumps(rooms, sort_keys=True).encode())
        rows.append({
            "floor_key": floor_id, "site_id": f"site-{index}", "building_id": f"building-{index}",
            "building_key": f"building-{index}", "plan_id": f"plan-{index}", "floor_id": floor_id,
            "split": split, "rendered_input_path": str(source / "image.png"),
            "output_hashes_sha256": {"image.png": _sha(source / "image.png")},
        })
    manifest = {
        "dataset": {"training_dataset_version": "test", "conversion_version": "test"},
        "summary": {"eligible_floors_by_split": {"train": 2, "val": 1, "test": 0},
                    "duplicate_relationships_crossing_splits": 0,
                    "duplicate_connected_clusters_crossing_splits": 0},
        "eligible_floors": rows, "exclusions": [],
    }
    source_path = tmp_path / "source-manifest.json"
    source_path.write_text(json.dumps(manifest, sort_keys=True))
    monkeypatch.setattr(adapter, "SOURCE_MANIFEST_SHA256", _sha(source_path))
    monkeypatch.setattr(adapter, "EXPECTED_FLOORS", 3)
    full_output = tmp_path / "full"
    result = adapter.build_full_adapter(source_path, full_output)
    monkeypatch.setattr(preflight, "FULL_MANIFEST_SHA256", result["manifest_sha256"])
    monkeypatch.setattr(preflight, "EXPECTED_FLOOR_COUNT", 3)
    return Path(result["manifest_path"])


def test_bundle_is_portable_deterministic_and_preserves_real_labels(tmp_path, monkeypatch):
    source = _fixture_manifest(tmp_path, monkeypatch)
    output = tmp_path / "bundle"
    first = preflight.build_kaggle_bundle(source, output)
    mtimes = {path: path.stat().st_mtime_ns for path in output.rglob("*") if path.is_file()}
    second = preflight.build_kaggle_bundle(source, output)
    assert first["bundle_sha256"] == second["bundle_sha256"]
    assert {path: path.stat().st_mtime_ns for path in output.rglob("*") if path.is_file()} == mtimes
    manifest = json.loads((output / "preflight-adapter-manifest.json").read_text())
    assert [row["split"] for row in manifest["floors"]] == ["train", "val", "train"]
    assert all(not Path(row["annotation_path"]).is_absolute() for row in manifest["floors"])
    hole = json.loads((output / manifest["floors"][0]["annotation_path"]).read_text())
    assert hole["annotations"][0]["interior_ring_count"] == 1
    negative = json.loads((output / manifest["floors"][2]["annotation_path"]).read_text())
    assert negative["annotations"] == []


def test_bundle_rejects_wrong_frozen_manifest_hash(tmp_path, monkeypatch):
    source = _fixture_manifest(tmp_path, monkeypatch)
    monkeypatch.setattr(preflight, "FULL_MANIFEST_SHA256", "0" * 64)
    with pytest.raises(ValueError, match="checksum mismatch"):
        preflight.build_kaggle_bundle(source, tmp_path / "bundle")


def test_inference_contract_requires_maskrcnn_fields():
    with pytest.raises(ValueError, match="missing keys"):
        preflight.validate_inference_output({"boxes": []}, [{"id": 1, "name": "bedroom"}])


def test_kaggle_python_312_runtime_is_required():
    preflight.require_python_version((3, 12))
    with pytest.raises(RuntimeError, match=r"Python 3\.12 required, found 3\.11"):
        preflight.require_python_version((3, 11))


def test_v2_notebook_evicts_cached_v1_modules_and_asserts_import_origin():
    notebook_path = Path(__file__).parents[1] / "ml" / "notebooks" / "maskrcnn_full_adapter_kaggle_preflight.ipynb"
    notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
    code = "\n".join("".join(cell.get("source", [])) for cell in notebook["cells"] if cell["cell_type"] == "code")
    assert "takeoff-task6-preflight-source-v2" in code
    assert "del sys.modules[module_name]" in code
    assert "importlib.invalidate_caches()" in code
    assert "sys.path.insert(0, str(backend_dir))" in code
    assert "module_path.is_relative_to(backend_dir)" in code
    assert "from ml.training.maskrcnn_kaggle_preflight import" not in code


def test_v2_source_has_no_python_311_runtime_guard():
    source = Path(preflight.__file__).read_text(encoding="utf-8")
    assert preflight.EXPECTED_PYTHON_VERSION == (3, 12)
    assert "Python 3.11 required" not in source
    assert "sys.version_info[:2] != (3, 11)" not in source


def _valid_gpu_report():
    losses = {
        "loss_box_reg": 0.2, "loss_classifier": 2.8, "loss_mask": 1.1,
        "loss_objectness": 0.7, "loss_rpn_box_reg": 0.3,
    }
    return {
        "preflight_version": preflight.PREFLIGHT_VERSION,
        "torch": "2.5.1+cu121", "torchvision": "0.20.1+cu121", "cuda": "12.1",
        "gpu": "Tesla T4", "vram_gib": 14.56, "dataset_samples": 3,
        "hole_instances_checked": 2, "intentional_negative_verified": True,
        "losses": losses, "total_loss": sum(losses.values()), "backward": True,
        "optimizer_step": True, "peak_allocated_gib": 3.8, "peak_reserved_gib": 4.7,
        "inference_contract": {
            "compatible": True, "prediction_count": 1,
            "mapped_example": {"label": "living", "score": 0.5, "bbox": [1, 2, 3, 4], "mask_shape": [10, 20]},
        },
        "training_started": False,
    }


def test_gpu_preflight_report_validator_accepts_complete_bounded_run():
    preflight.validate_gpu_preflight_report(_valid_gpu_report())


@pytest.mark.parametrize("field,value", [
    ("backward", False), ("optimizer_step", False), ("training_started", True),
    ("peak_reserved_gib", 15.0), ("dataset_samples", 2),
])
def test_gpu_preflight_report_validator_rejects_incomplete_evidence(field, value):
    report = _valid_gpu_report()
    report[field] = value
    with pytest.raises(ValueError):
        preflight.validate_gpu_preflight_report(report)
