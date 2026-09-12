"""Small-fixture tests for the read-only CubiCasa5K audit."""

import json

from PIL import Image

from ml.datasets.audit_cubicasa5k import audit_cubicasa


SVG = """<svg xmlns="http://www.w3.org/2000/svg">
<g class="Space LivingRoom"><polygon points="0,0 10,0 10,10 0,10"/></g>
<g class="Wall External"><polygon points="0,0 1,0 1,10 0,10"/></g>
<g class="Door Swing"><polygon points="0,0 1,0 1,1"/></g>
<g class="Window Regular"><polygon points="0,0 1,0 1,1"/></g>
<g class="FixedFurniture Toilet"><g class="BoundaryPolygon"><polygon points="0,0 1,0 1,1"/></g></g>
</svg>"""


def _plan(root, category, plan_id, color):
    directory = root / category / plan_id
    directory.mkdir(parents=True)
    Image.new("RGB", (16, 16), color).save(directory / "F1_original.png")
    Image.new("RGB", (8, 8), color).save(directory / "F1_scaled.png")
    (directory / "model.svg").write_text(SVG, encoding="utf-8")


def test_audit_counts_splits_taxonomy_and_integrity(tmp_path):
    _plan(tmp_path, "high_quality", "1", "white")
    _plan(tmp_path, "colorful", "2", "blue")
    (tmp_path / "train.txt").write_text("/high_quality/1/\n", encoding="utf-8")
    (tmp_path / "val.txt").write_text("/colorful/2/\n", encoding="utf-8")
    (tmp_path / "test.txt").write_text("", encoding="utf-8")

    report = audit_cubicasa(tmp_path, workers=1)

    assert report["counts"]["plans_with_model_svg"] == 2
    assert report["counts"]["floor_pages_original"] == 2
    assert report["splits"]["plan_counts"] == {"train": 1, "val": 1, "test": 0}
    assert report["taxonomy"]["spaces"] == {"LivingRoom": 2}
    assert report["taxonomy"]["walls"] == {"External": 2}
    assert report["taxonomy"]["doors"] == {"Swing": 2}
    assert report["taxonomy"]["windows"] == {"Regular": 2}
    assert report["taxonomy"]["fixed_furniture"] == {"Toilet": 2}
    assert report["integrity"]["png_errors"] == []
    assert report["integrity"]["svg_errors"] == []


def test_audit_reports_duplicate_and_missing_pair(tmp_path):
    _plan(tmp_path, "high_quality", "1", "white")
    second = tmp_path / "high_quality" / "2"
    second.mkdir(parents=True)
    (second / "F1_original.png").write_bytes((tmp_path / "high_quality" / "1" / "F1_original.png").read_bytes())
    (second / "model.svg").write_text(SVG, encoding="utf-8")
    for split, content in (("train", "/high_quality/1/\n"), ("val", "/high_quality/2/\n"), ("test", "")):
        (tmp_path / f"{split}.txt").write_text(content, encoding="utf-8")

    report = audit_cubicasa(tmp_path, workers=1)

    assert len(report["integrity"]["duplicate_png_groups"]) == 1
    assert report["integrity"]["missing_original_scaled_pairs"] == [
        {"plan": "high_quality/2", "missing_original": [], "missing_scaled": ["1"]}
    ]
    json.dumps(report)
