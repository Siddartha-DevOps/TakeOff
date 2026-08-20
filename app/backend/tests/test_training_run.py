"""Tests for the Phase 3 training config + gated runner (no ultralytics/GPU)."""

import struct

import pytest

from ml.training.config import TASK_WEIGHTS, TrainConfig
from ml.training.run_training import (
    build_train_plan,
    promote_weights,
    resolve_best_weights,
    run,
)


# --- config validation -----------------------------------------------------
def test_defaults_valid_and_construction_tuned():
    c = TrainConfig().validate()
    assert c.task == "spaces" and c.imgsz == 1280  # large-sheet default


def test_invalid_imgsz_rejected():
    with pytest.raises(ValueError):
        TrainConfig(imgsz=300).validate()   # not a multiple of 32


def test_invalid_task_and_epochs_rejected():
    with pytest.raises(ValueError):
        TrainConfig(task="walls").validate()
    with pytest.raises(ValueError):
        TrainConfig(epochs=0).validate()


def test_from_dict_ignores_unknown_keys():
    c = TrainConfig.from_dict({"task": "symbols", "epochs": 50, "bogus": 1})
    assert c.task == "symbols" and c.epochs == 50


def test_smoke_config_is_fast():
    c = TrainConfig.smoke()
    assert c.epochs == 1 and c.imgsz == 320 and c.batch == 2


def test_weights_target_per_task():
    assert TrainConfig(task="spaces").weights_target() == TASK_WEIGHTS["spaces"]
    assert TrainConfig(task="symbols").weights_target() == TASK_WEIGHTS["symbols"]
    assert TrainConfig(task="spaces").weights_target().name == "best.pt"


def test_train_kwargs_shape_and_device_override():
    kw = TrainConfig().train_kwargs("d/data.yaml", device="cuda:0")
    assert kw["task"] == "segment" and kw["data"] == "d/data.yaml"
    assert kw["device"] == "cuda:0" and kw["exist_ok"] is True
    assert kw["name"].endswith("_spaces")


# --- gating (build_train_plan) --------------------------------------------
def _dataset(tmp_path):
    (tmp_path / "labels" / "train").mkdir(parents=True)
    (tmp_path / "labels" / "train" / "a.txt").write_text("0 0 0 1 0 1 1")
    (tmp_path / "data.yaml").write_text("nc: 1\nnames:\n  0: living\n")
    return tmp_path / "data.yaml"


def test_plan_blocks_on_missing_dataset(tmp_path):
    plan = build_train_plan(TrainConfig(), tmp_path / "nope.yaml", require_deps=False)
    assert plan["ready"] is False
    assert any("dataset not found" in b for b in plan["blockers"])


def test_plan_ready_with_dataset_when_deps_not_required(tmp_path):
    plan = build_train_plan(TrainConfig(), _dataset(tmp_path), require_deps=False)
    assert plan["ready"] is True and plan["blockers"] == []


def test_plan_blocks_on_missing_deps(tmp_path):
    # CI has no torch/ultralytics -> require_deps must block.
    plan = build_train_plan(TrainConfig(), _dataset(tmp_path), require_deps=True)
    assert plan["ready"] is False
    assert any("missing dependency" in b for b in plan["blockers"])


def test_run_raises_when_gate_fails(tmp_path):
    # No dataset -> run() must refuse before importing ultralytics (never fakes weights).
    with pytest.raises(RuntimeError, match="training blocked"):
        run(TrainConfig(), tmp_path / "missing.yaml", require_deps=False)


# --- weights promotion -----------------------------------------------------
def test_resolve_best_prefers_best_then_last(tmp_path):
    wd = tmp_path / "run" / "weights"
    wd.mkdir(parents=True)
    (wd / "last.pt").write_bytes(b"L")
    assert resolve_best_weights(tmp_path / "run").name == "last.pt"
    (wd / "best.pt").write_bytes(b"B")
    assert resolve_best_weights(tmp_path / "run").name == "best.pt"


def test_resolve_best_none_when_absent(tmp_path):
    assert resolve_best_weights(tmp_path / "empty") is None


def test_promote_copies_to_target(tmp_path):
    best = tmp_path / "weights" / "best.pt"
    best.parent.mkdir(parents=True)
    best.write_bytes(b"WEIGHTS")
    target = tmp_path / "models" / "best.pt"
    out = promote_weights(best, target)
    assert out.read_bytes() == b"WEIGHTS" and out == target


def test_module_imports_without_ultralytics():
    # Guard: importing the runner must not require the heavy stack.
    import importlib
    import ml.training.run_training as m
    importlib.reload(m)
    assert hasattr(m, "run")
