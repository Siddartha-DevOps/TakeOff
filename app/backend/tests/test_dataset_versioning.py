"""Tests for content-addressed dataset versioning."""

from ml.datasets.versioning import (
    build_manifest,
    bytes_digest,
    diff_manifests,
    load_version,
    manifest_id,
    snapshot_dataset,
    write_version,
)


def test_manifest_is_order_independent():
    a = build_manifest([("b.txt", "h2", 2), ("a.txt", "h1", 1)])
    b = build_manifest([("a.txt", "h1", 1), ("b.txt", "h2", 2)])
    assert a == b
    assert manifest_id(a) == manifest_id(b)
    assert a["file_count"] == 2 and a["total_bytes"] == 3


def test_manifest_id_changes_when_content_changes():
    base = build_manifest([("a.txt", "h1", 1)])
    edited = build_manifest([("a.txt", "DIFFERENT", 1)])
    assert manifest_id(base) != manifest_id(edited)


def test_diff_reports_add_remove_change():
    old = build_manifest([("a.txt", "h1", 1), ("b.txt", "h2", 1)])
    new = build_manifest([("a.txt", "h1", 1), ("b.txt", "CHANGED", 1), ("c.txt", "h3", 1)])
    d = diff_manifests(old, new)
    assert d["added"] == ["c.txt"] and d["removed"] == [] and d["changed"] == ["b.txt"]


def test_snapshot_and_reload_roundtrip(tmp_path):
    # Build a tiny YOLO-seg dataset layout.
    (tmp_path / "labels" / "train").mkdir(parents=True)
    (tmp_path / "labels" / "val").mkdir(parents=True)
    (tmp_path / "images" / "train").mkdir(parents=True)
    (tmp_path / "labels" / "train" / "a.txt").write_text("0 0 0 1 0 1 1")
    (tmp_path / "labels" / "train" / "b.txt").write_text("1 0 0 1 0 1 1")
    (tmp_path / "labels" / "val" / "c.txt").write_text("0 0 0 1 0 1 1")
    (tmp_path / "images" / "train" / "a.png").write_bytes(b"\x89PNG fake")

    v = snapshot_dataset(tmp_path, name="spaces", created_at="2026-07-18T00:00:00Z",
                         class_names=["living", "bedroom"])
    assert v.splits == {"train": 2, "val": 1}
    assert len(v.id) == 16
    assert v.manifest["file_count"] == 4

    out = tmp_path / "version.json"
    write_version(v, out)
    reloaded = load_version(out)
    assert reloaded.id == v.id and reloaded.splits == v.splits


def test_identical_bytes_same_id_across_snapshots(tmp_path):
    for d in ("d1", "d2"):
        (tmp_path / d / "labels" / "train").mkdir(parents=True)
        (tmp_path / d / "labels" / "train" / "a.txt").write_text("0 0 0 1 0 1 1")
    v1 = snapshot_dataset(tmp_path / "d1", name="x", created_at="t")
    v2 = snapshot_dataset(tmp_path / "d2", name="y", created_at="t2")
    assert v1.id == v2.id  # content-addressed: same bytes -> same id regardless of name


def test_bytes_digest_stable():
    assert bytes_digest(b"abc") == bytes_digest(b"abc")
    assert bytes_digest(b"abc") != bytes_digest(b"abd")
