"""Tests for CubiCasa5K → versioned YOLO-seg dataset conversion (Phase 2)."""

import struct

import pytest

from ml.datasets.acquire_cubicasa import (
    build_and_version_cubicasa,
    convert_cubicasa_dataset,
    parse_cubicasa_svg,
    png_dimensions,
    svg_polygon_points,
)
from ml.datasets.bootstrap_public import class_id

# A minimal CubiCasa-style model.svg: two rooms (Space groups) + a Wall group
# (which must be dropped by the space remap).
SAMPLE_SVG = """<svg xmlns="http://www.w3.org/2000/svg">
  <g class="Space LivingRoom ">
    <polygon points="0,0 200,0 200,200 0,200" />
  </g>
  <g class="Space Bedroom">
    <polygon points="200,0 400,0 400,200 200,200" />
  </g>
  <g class="Wall">
    <polygon points="0,0 400,0 400,10 0,10" />
  </g>
</svg>"""


def _fake_png(path, width, height):
    """Write a byte-minimal but valid-headered PNG (only IHDR matters here)."""
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = b"IHDR" + struct.pack(">II", width, height) + b"\x08\x06\x00\x00\x00"
    path.write_bytes(sig + struct.pack(">I", 13) + ihdr)


# --- pure parsers ----------------------------------------------------------
def test_svg_polygon_points_comma_and_space():
    assert svg_polygon_points("0,0 10,0 10,10") == [[0, 0], [10, 0], [10, 10]]
    assert svg_polygon_points("0 0 10 0 10 10") == [[0, 0], [10, 0], [10, 10]]


def test_parse_cubicasa_svg_extracts_rooms_and_walls():
    parsed = parse_cubicasa_svg(SAMPLE_SVG)
    labels = [lbl for lbl, _ in parsed]
    assert "LivingRoom" in labels and "Bedroom" in labels and "Wall" in labels
    # LivingRoom polygon is the unit square scaled to 200.
    living = next(ring for lbl, ring in parsed if lbl == "LivingRoom")
    assert living[2] == [200, 200]


def test_parse_cubicasa_svg_bad_xml_is_empty():
    assert parse_cubicasa_svg("<not valid") == []


def test_png_dimensions_reads_header(tmp_path):
    p = tmp_path / "F1_original.png"
    _fake_png(p, 640, 480)
    assert png_dimensions(p) == (640, 480)


def test_png_dimensions_rejects_non_png(tmp_path):
    p = tmp_path / "x.png"
    p.write_bytes(b"not a png at all........")
    with pytest.raises(ValueError):
        png_dimensions(p)


# --- conversion ------------------------------------------------------------
def _make_sample(root, name, width=400, height=200, svg=SAMPLE_SVG):
    d = root / name
    d.mkdir(parents=True)
    (d / "model.svg").write_text(svg)
    _fake_png(d / "F1_original.png", width, height)
    return d


def test_convert_writes_labels_yaml_and_drops_walls(tmp_path):
    src = tmp_path / "cubicasa"
    _make_sample(src, "sample_0")
    out = tmp_path / "dataset"

    summary = convert_cubicasa_dataset(src, out, val_every=1)  # all -> val
    assert summary["val"] == 1 and summary["rooms"] == 2      # 2 rooms, Wall dropped

    label_file = out / "labels" / "val" / "sample_0.txt"
    assert label_file.exists()
    lines = label_file.read_text().splitlines()
    assert len(lines) == 2
    class_ids = {int(l.split()[0]) for l in lines}
    assert class_ids == {class_id("living"), class_id("bedroom")}

    assert (out / "images" / "val" / "sample_0.png").exists()
    assert (out / "data.yaml").exists()


def test_convert_skips_sample_with_no_mappable_rooms(tmp_path):
    src = tmp_path / "cubicasa"
    only_wall = '<svg xmlns="http://www.w3.org/2000/svg"><g class="Wall">' \
                '<polygon points="0,0 10,0 10,10"/></g></svg>'
    _make_sample(src, "wall_only", svg=only_wall)
    out = tmp_path / "dataset"
    summary = convert_cubicasa_dataset(src, out)
    assert summary["dropped"] == 1 and summary["train"] == 0 and summary["val"] == 0


def test_convert_train_val_split(tmp_path):
    src = tmp_path / "cubicasa"
    for i in range(5):
        _make_sample(src, f"s{i}")
    out = tmp_path / "dataset"
    summary = convert_cubicasa_dataset(src, out, val_every=5)  # index 0 -> val, rest train
    assert summary["val"] == 1 and summary["train"] == 4


def test_build_and_version_produces_dataset_version(tmp_path):
    src = tmp_path / "cubicasa"
    _make_sample(src, "s0")
    _make_sample(src, "s1")
    out = tmp_path / "dataset"

    summary, version = build_and_version_cubicasa(
        src, out, created_at="2026-07-18T00:00:00Z", val_every=2,
    )
    assert summary["train"] + summary["val"] == 2
    assert len(version.id) == 16
    assert version.name == "cubicasa-spaces"
    assert (out / "dataset_version.json").exists()
    # Version is content-addressed over the produced labels/images/yaml.
    assert version.manifest["file_count"] >= 3
