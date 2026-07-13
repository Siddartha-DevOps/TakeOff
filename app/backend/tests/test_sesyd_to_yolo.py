"""Tests for the SESYD -> YOLO detection conversion (training/sesyd_to_yolo.py)."""

import sys
import types

from training.sesyd_to_yolo import parse_sesyd_objects, sesyd_to_yolo

VALID_XML = """<annotation>
  <object><name>Door</name><bndbox><xmin>10</xmin><ymin>20</ymin><xmax>30</xmax><ymax>60</ymax></bndbox></object>
  <object><name>sink</name><bndbox><xmin>0</xmin><ymin>0</ymin><xmax>10</xmax><ymax>10</ymax></bndbox></object>
  <object><bndbox><xmin>0</xmin><ymin>0</ymin><xmax>1</xmax><ymax>1</ymax></bndbox></object>
  <object><name>table</name></object>
</annotation>"""


def test_parse_sesyd_objects_lowercases_name_and_skips_malformed(tmp_path):
    xml_path = tmp_path / "plan.xml"
    xml_path.write_text(VALID_XML)

    objects = parse_sesyd_objects(xml_path)

    assert objects == [
        {"name": "door", "bbox": (10.0, 20.0, 30.0, 60.0)},
        {"name": "sink", "bbox": (0.0, 0.0, 10.0, 10.0)},
    ]


def _install_fake_pil(monkeypatch, size=(200, 100)):
    """Stand in for Pillow (not part of this repo's lightweight test deps)."""

    class FakeImage:
        def __init__(self, s):
            self.size = s

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    fake_pil = types.ModuleType("PIL")
    fake_pil.Image = types.SimpleNamespace(open=lambda path: FakeImage(size))
    monkeypatch.setitem(sys.modules, "PIL", fake_pil)


def test_sesyd_to_yolo_end_to_end(tmp_path, monkeypatch):
    _install_fake_pil(monkeypatch, size=(200, 100))

    sesyd_root = tmp_path / "SESYD"
    sesyd_root.mkdir()
    (sesyd_root / "plan_0001.xml").write_text(VALID_XML)
    (sesyd_root / "plan_0001.png").write_bytes(b"")  # existence is all that's checked

    # An XML with no image next to it should be counted as skipped, not crash.
    (sesyd_root / "plan_0002.xml").write_text(VALID_XML)

    # An XML whose objects don't overlap SYMBOL_CLASSES should also be skipped.
    (sesyd_root / "plan_0003.xml").write_text(
        "<annotation><object><name>table</name></object></annotation>"
    )
    (sesyd_root / "plan_0003.png").write_bytes(b"")

    output_dir = tmp_path / "out"
    summary = sesyd_to_yolo(sesyd_root, output_dir)

    assert summary == {"images": 1, "boxes": 2, "skipped": 2}
    label_text = (output_dir / "labels" / "plan_0001.txt").read_text()
    assert label_text.splitlines() == [
        "0 0.100000 0.400000 0.100000 0.400000",  # door: cls_id 0
        "2 0.025000 0.050000 0.050000 0.100000",  # sink: cls_id 2
    ]
    assert (output_dir / "images" / "plan_0001.png").is_symlink()
    assert not (output_dir / "labels" / "plan_0003.txt").exists()


def test_sesyd_to_yolo_rerun_is_safe(tmp_path, monkeypatch):
    """Re-running against the same output dir must not raise FileExistsError."""
    _install_fake_pil(monkeypatch)

    sesyd_root = tmp_path / "SESYD"
    sesyd_root.mkdir()
    (sesyd_root / "plan.xml").write_text(VALID_XML)
    (sesyd_root / "plan.png").write_bytes(b"")

    output_dir = tmp_path / "out"
    sesyd_to_yolo(sesyd_root, output_dir)
    summary = sesyd_to_yolo(sesyd_root, output_dir)  # should not raise

    assert summary == {"images": 1, "boxes": 2, "skipped": 0}
