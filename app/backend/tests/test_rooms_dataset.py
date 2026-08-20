"""Tests for the room-type segmentation dataset scaffolding (pure functions)."""

from training.rooms_dataset import ROOM_CLASSES, build_rooms_yaml


def test_room_classes_match_detection_engine_room_ids():
    """rooms_dataset.ROOM_CLASSES must stay in lock-step with the engine's class ids 0-8."""
    from ai.detection_engine import CLASS_NAMES, ROOM_CLASSES as ENGINE_ROOM_IDS

    engine_rooms = [CLASS_NAMES[i] for i in sorted(ENGINE_ROOM_IDS)]
    assert ROOM_CLASSES == engine_rooms


def test_build_rooms_yaml_writes_expected_yaml(tmp_path):
    out = build_rooms_yaml(tmp_path)

    assert out == tmp_path / "rooms.yaml"
    text = out.read_text()
    assert f"path: {tmp_path}" in text
    assert "train: images/train" in text
    assert "val: images/val" in text
    assert "nc: 9" in text
    for i, name in enumerate(ROOM_CLASSES):
        assert f"  {i}: {name}" in text


def test_build_rooms_yaml_creates_dataset_dir(tmp_path):
    dataset_dir = tmp_path / "rooms_yolo"
    assert not dataset_dir.exists()

    build_rooms_yaml(dataset_dir)

    assert dataset_dir.is_dir()
    assert (dataset_dir / "rooms.yaml").exists()
