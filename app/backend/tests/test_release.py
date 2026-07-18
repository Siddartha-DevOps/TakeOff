"""Tests for Phase 5 release/deploy helpers (no DB / no torch)."""

import pytest

from ml.registry.release import (
    pick_active,
    serving_readiness,
    stage_weights,
)
from ml.training.config import TASK_WEIGHTS


# --- active-weights selection ---------------------------------------------
def test_pick_active_returns_active_uri():
    rows = [
        {"stage": "CANDIDATE", "weights_uri": "s3://old"},
        {"stage": "ACTIVE", "weights_uri": "s3://current"},
    ]
    assert pick_active(rows) == "s3://current"


def test_pick_active_none_when_no_active():
    assert pick_active([{"stage": "CANDIDATE", "weights_uri": "x"}]) is None
    assert pick_active([]) is None


# --- weights staging -------------------------------------------------------
def test_stage_weights_copies_to_task_path(tmp_path, monkeypatch):
    src = tmp_path / "run" / "best.pt"
    src.parent.mkdir()
    src.write_bytes(b"WEIGHTS")
    target = tmp_path / "models" / "best.pt"
    monkeypatch.setitem(TASK_WEIGHTS, "spaces", target)

    out = stage_weights(src, task="spaces")
    assert out == target and out.read_bytes() == b"WEIGHTS"


def test_stage_weights_missing_source_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        stage_weights(tmp_path / "nope.pt", target=tmp_path / "out.pt")


def test_stage_weights_explicit_target(tmp_path):
    src = tmp_path / "best.pt"
    src.write_bytes(b"W")
    target = tmp_path / "sub" / "dir" / "model.pt"
    assert stage_weights(src, target=target).read_bytes() == b"W"


# --- serving readiness -----------------------------------------------------
def test_serving_not_ready_without_weights(tmp_path):
    r = serving_readiness(task="spaces", weights_path=tmp_path / "absent.pt")
    assert r["ready"] is False
    assert any("no trained weights" in b for b in r["blockers"])


def test_serving_weights_blocker_clears_when_present(tmp_path):
    wp = tmp_path / "best.pt"
    wp.write_bytes(b"W")
    r = serving_readiness(task="spaces", weights_path=wp)
    # In CI (no torch/ultralytics) it's still not fully ready, but the WEIGHTS
    # blocker must be gone — proving the weights path is recognized.
    assert r["weights"]["exists"] is True
    assert not any("no trained weights" in b for b in r["blockers"])
