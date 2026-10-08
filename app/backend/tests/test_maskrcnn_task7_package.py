import hashlib
import inspect
import json
import zipfile
from pathlib import Path

import pytest

from ml.training import maskrcnn_task7_package as package
from ml.training.maskrcnn_task7_train import (
    _capture_rng_state,
    _cpu_byte_rng_state,
    _epoch_loader_runtime,
    _load_checkpoint,
    _loader_process_options,
    _resume_position,
    _restore_rng_state,
    _should_checkpoint_in_epoch,
    _should_emit_heartbeat,
    _should_log_progress,
    _step_optimizer_with_amp,
    _training_step_counts,
    _unscaled_loss_value,
    parse_args,
    train,
)


class _FakeOptimizer:
    def __init__(self):
        self.step_calls = 0

    def step(self):
        self.step_calls += 1


class _FakeScheduler:
    def __init__(self):
        self.step_calls = 0

    def step(self):
        self.step_calls += 1


class _FakeScaler:
    def __init__(self, *, scale_before, scale_after, perform_optimizer_step):
        self.scale = scale_before
        self.scale_after = scale_after
        self.perform_optimizer_step = perform_optimizer_step

    def get_scale(self):
        return self.scale

    def step(self, optimizer):
        if self.perform_optimizer_step:
            optimizer.step()

    def update(self):
        self.scale = self.scale_after


class _FakeLoss:
    def __init__(self, value):
        self.value = value
        self.detached = False

    def detach(self):
        self.detached = True
        return self

    def item(self):
        assert self.detached
        return self.value

    def __float__(self):
        raise AssertionError("loss must be detached before scalar conversion")


def _write_fixture(tmp_path):
    root = tmp_path / "adapter"
    floors = []
    for split, building in (("train", "a"), ("val", "b"), ("test", "c")):
        (root / "images" / split).mkdir(parents=True, exist_ok=True)
        (root / "annotations" / split).mkdir(parents=True, exist_ok=True)
        image = root / "images" / split / f"{split}.png"
        annotation = root / "annotations" / split / f"{split}.json"
        image.write_bytes(b"image")
        annotation.write_text("{}")
        floors.append({
            "split": split, "building_key": building,
            "image_path": f"Z:\\external\\images\\{split}.png",
            "annotation_path": f"Z:\\external\\annotations\\{split}.json",
        })
    manifest = {
        "taxonomy": [{"id": index + 1, "name": name} for index, name in enumerate(package.EXPECTED_TAXONOMY)],
        "floors": floors,
        "summary": {
            "floors_by_split": {"train": 1, "val": 1, "test": 1},
            "building_leakage_count": 0,
            "duplicate_relationships_crossing_splits": 0,
            "duplicate_connected_clusters_crossing_splits": 0,
            "rejected_instance_count": 0,
            "authoritative_instance_count": 3,
            "hole_instance_count": 1,
            "intentional_negative_floor_count": 1,
        },
    }
    manifest_path = root / "full-adapter-manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True))
    weights = tmp_path / "weights.pth"
    weights.write_bytes(b"weights")
    config = {
        "run_id": "test", "taxonomy": package.EXPECTED_TAXONOMY,
        "dataset": {
            "adapter_manifest_filename": manifest_path.name,
            "adapter_manifest_sha256": package.sha256_file(manifest_path),
            "test_policy": "LOCKED_UNTOUCHED_UNTIL_FINAL_EVALUATION",
        },
        "initialization": {"sha256": package.sha256_file(weights)},
        "runtime": {}, "training": {}, "evaluation": {}, "acceptance": {},
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))
    return config_path, root, weights


def test_package_validation_enforces_hashes_assets_splits_and_test_lock(tmp_path, monkeypatch):
    config, root, weights = _write_fixture(tmp_path)
    monkeypatch.setattr(package, "EXPECTED_SPLITS", {"train": 1, "val": 1, "test": 1})
    result = package.validate_package(config, root, weights)
    assert result["status"] == "PASS"
    assert result["missing_assets"] == 0
    assert result["test_labels_read"] is False
    weights.write_bytes(b"changed")
    with pytest.raises(ValueError, match="initialization checkpoint checksum"):
        package.validate_package(config, root, weights)


def test_portable_basename_maps_windows_manifest_paths_on_linux_layout():
    assert package.portable_basename(r"E:\adapter\images\train\floor.png") == "floor.png"
    assert package.portable_basename("/adapter/images/train/floor.png") == "floor.png"


def test_source_bundle_is_byte_deterministic(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    one = package.build_source_zip(tmp_path, tmp_path / "one.zip", ["b.txt", "a.txt"])
    two = package.build_source_zip(tmp_path, tmp_path / "two.zip", ["a.txt", "b.txt"])
    assert hashlib.sha256(one.read_bytes()).digest() == hashlib.sha256(two.read_bytes()).digest()


def test_external_package_manifest_is_content_addressed(tmp_path):
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"verified")
    manifest = package.write_kaggle_package_manifest(
        tmp_path / "package.json", {"dataset": artifact}
    )
    payload = json.loads(manifest.read_text())
    assert payload["status"] == "FROZEN_NOT_STARTED"
    assert payload["artifacts"][0]["sha256"] == package.sha256_file(artifact)


def test_zip_and_extracted_directory_have_identical_tree_hash(tmp_path):
    source = tmp_path / "source"
    (source / "nested").mkdir(parents=True)
    (source / "a.txt").write_text("alpha")
    (source / "nested" / "b.txt").write_text("beta")
    archive = package.build_source_zip(
        source, tmp_path / "source.zip", ["nested/b.txt", "a.txt"]
    )
    extracted = tmp_path / "extracted"
    with zipfile.ZipFile(archive) as handle:
        handle.extractall(extracted)
    assert package.zip_tree_sha256(archive) == package.directory_tree_sha256(extracted)
    manifest = package.write_kaggle_package_manifest(
        tmp_path / "package.json", {"source": archive}
    )
    artifact = json.loads(manifest.read_text())["artifacts"][0]
    assert artifact["extracted_tree_sha256"] == package.directory_tree_sha256(extracted)[0]
    assert artifact["extracted_file_count"] == 2


def test_training_cli_defaults_to_locked_mode():
    args = parse_args(["--config", "c", "--adapter-root", "a", "--initialization", "w", "--output", "o"])
    assert args.authorize_training is False
    assert args.validate_only is False
    assert args.diagnostic_max_batches is None
    assert args.diagnostic_num_workers == 0
    assert args.num_workers == 0
    assert args.heartbeat_every_batches == 10
    assert args.checkpoint_every_optimizer_updates == 50


def test_amp_overflow_does_not_advance_scheduler():
    optimizer = _FakeOptimizer()
    scheduler = _FakeScheduler()
    scaler = _FakeScaler(
        scale_before=65536.0, scale_after=32768.0, perform_optimizer_step=False,
    )
    result = _step_optimizer_with_amp(
        scaler=scaler, optimizer=optimizer, scheduler=scheduler,
    )
    assert result == {
        "optimizer_step_performed": False,
        "grad_scale_before": 65536.0,
        "grad_scale_after": 32768.0,
    }
    assert optimizer.step_calls == 0
    assert scheduler.step_calls == 0


def test_successful_amp_update_advances_scheduler_once():
    optimizer = _FakeOptimizer()
    scheduler = _FakeScheduler()
    scaler = _FakeScaler(
        scale_before=32768.0, scale_after=32768.0, perform_optimizer_step=True,
    )
    result = _step_optimizer_with_amp(
        scaler=scaler, optimizer=optimizer, scheduler=scheduler,
    )
    assert result["optimizer_step_performed"] is True
    assert optimizer.step_calls == 1
    assert scheduler.step_calls == 1


def test_loss_logging_detaches_and_progress_includes_skips():
    loss = _FakeLoss(2.5)
    assert _unscaled_loss_value(loss, 4) == 10.0
    assert _should_log_progress(optimizer_attempts=2, skipped=True, final_batch=False)
    assert _should_log_progress(optimizer_attempts=100, skipped=False, final_batch=False)
    assert not _should_log_progress(optimizer_attempts=2, skipped=False, final_batch=False)


def test_mid_epoch_checkpoint_resume_position_and_cadence():
    assert _resume_position({"epoch": 2, "epoch_complete": True}) == (3, 0, 0.0)
    assert _resume_position({
        "epoch": 2,
        "epoch_complete": False,
        "next_batch_index": 401,
        "epoch_running_loss": 123.5,
    }) == (2, 401, 123.5)
    assert _should_checkpoint_in_epoch(optimizer_updates=50, interval=50)
    assert not _should_checkpoint_in_epoch(optimizer_updates=49, interval=50)
    assert not _should_checkpoint_in_epoch(optimizer_updates=50, interval=0)


def test_existing_mid_epoch_checkpoint_position_remains_compatible():
    checkpoint = {
        "epoch": 0,
        "epoch_complete": False,
        "next_batch_index": 212,
        "epoch_running_loss": 987.5,
        "optimizer_updates": 50,
    }
    assert _resume_position(checkpoint) == (0, 212, 987.5)
    assert checkpoint["optimizer_updates"] == 50


def test_heartbeat_and_loader_resource_safety_defaults():
    assert _should_emit_heartbeat(completed_batches=10, interval=10, final_batch=False)
    assert _should_emit_heartbeat(completed_batches=13, interval=10, final_batch=True)
    assert not _should_emit_heartbeat(completed_batches=9, interval=10, final_batch=False)
    assert _loader_process_options(0) == {
        "num_workers": 0, "persistent_workers": False,
    }
    assert _loader_process_options(2) == {
        "num_workers": 2, "persistent_workers": False,
        "prefetch_factor": 1, "timeout": 120,
    }
    with pytest.raises(ValueError, match="non-negative"):
        _loader_process_options(-1)


def test_training_and_validation_paths_both_emit_heartbeats():
    source = inspect.getsource(train)
    evaluation_source = inspect.getsource(
        __import__(
            "ml.training.maskrcnn_task7_train", fromlist=["_evaluate"]
        )._evaluate
    )
    assert '"event": "training_heartbeat"' in source
    assert '"event": "validation_heartbeat"' in evaluation_source


def test_rng_state_round_trip_supports_reliable_resume():
    import numpy as np

    class FakeTensor:
        def __init__(self, value, *, device="cuda", dtype="wrong", shape=None):
            self.value, self.device, self.dtype = value, device, dtype
            self.shape = shape

        def detach(self):
            return self

        def cpu(self):
            return FakeTensor(self.value, device="cpu", dtype=self.dtype, shape=self.shape)

        def clone(self):
            return FakeTensor(self.value, device=self.device, dtype=self.dtype, shape=self.shape)

        def to(self, *, device, dtype):
            return FakeTensor(self.value, device=device, dtype=dtype, shape=self.shape)

        def contiguous(self):
            return self

    class FakeCuda:
        restored = None

        @staticmethod
        def is_available():
            return True

        @classmethod
        def get_rng_state_all(cls):
            return [
                FakeTensor(b"cuda-0", device="cuda", dtype="uint8", shape=(16,)),
                FakeTensor(b"cuda-1", device="cuda", dtype="uint8", shape=(16,)),
            ]

        @classmethod
        def set_rng_state_all(cls, states):
            cls.restored = states

    class FakeTorch:
        uint8 = "uint8"
        cuda = FakeCuda()
        state = FakeTensor(b"initial")

        @staticmethod
        def is_tensor(value):
            return isinstance(value, FakeTensor)

        @staticmethod
        def as_tensor(value):
            return FakeTensor(value)

        @classmethod
        def get_rng_state(cls):
            return cls.state

        @classmethod
        def set_rng_state(cls, state):
            if state.device != "cpu" or state.dtype != cls.uint8:
                raise TypeError("RNG state must be a torch.ByteTensor")
            cls.state = state

    random_seed = 2718
    import random
    random.seed(random_seed)
    np.random.seed(random_seed)
    FakeTorch.state = FakeTensor(b"saved", device="cpu", dtype="uint8", shape=(5056,))
    state = _capture_rng_state(FakeTorch)
    expected = (random.random(), float(np.random.random()), b"saved")
    FakeTorch.state = FakeTensor(b"changed")
    assert _restore_rng_state(state, FakeTorch)
    actual = (random.random(), float(np.random.random()), FakeTorch.state.value)
    assert actual == expected
    assert FakeTorch.state.device == "cpu"
    assert FakeTorch.state.dtype == FakeTorch.uint8
    assert FakeTorch.state.shape == (5056,)
    assert len(FakeCuda.restored) == 2
    assert FakeCuda.restored[0].device == "cpu"
    assert FakeCuda.restored[0].dtype == FakeTorch.uint8
    assert FakeCuda.restored[0].shape == (16,)
    assert FakeCuda.restored[1].shape == (16,)
    assert not _restore_rng_state(None, FakeTorch)


def test_original_cuda_remap_failure_is_reproduced_and_recovered():
    class FakeTensor:
        def __init__(self, *, device, dtype):
            self.device, self.dtype = device, dtype

        def detach(self):
            return self

        def to(self, *, device, dtype):
            return FakeTensor(device=device, dtype=dtype)

        def contiguous(self):
            return self

    class FakeCuda:
        restored = None

        @staticmethod
        def is_available():
            return True

        @classmethod
        def set_rng_state_all(cls, values):
            cls.restored = values

    class FakeTorch:
        uint8 = "uint8"
        cuda = FakeCuda()
        restored = None

        @staticmethod
        def is_tensor(value):
            return isinstance(value, FakeTensor)

        @classmethod
        def set_rng_state(cls, value):
            if value.device != "cpu" or value.dtype != cls.uint8:
                raise TypeError("RNG state must be a torch.ByteTensor")
            cls.restored = value

    remapped = FakeTensor(device="cuda:0", dtype="uint8")
    with pytest.raises(TypeError, match="RNG state must be a torch.ByteTensor"):
        FakeTorch.set_rng_state(remapped)

    import random
    import numpy as np
    state = {
        "python": random.getstate(),
        "numpy": np.random.get_state(),
        "torch_cpu": remapped,
        "torch_cuda": [
            FakeTensor(device="cuda:0", dtype="uint8"),
            FakeTensor(device="cuda:1", dtype="uint8"),
        ],
    }
    assert _restore_rng_state(state, FakeTorch)
    assert FakeTorch.restored.device == "cpu"
    assert all(value.device == "cpu" for value in FakeCuda.restored)


def test_checkpoint_load_keeps_rng_and_optimizer_tensors_on_cpu():
    class FakeTorch:
        call = None

        @classmethod
        def load(cls, path, **kwargs):
            cls.call = (path, kwargs)
            return {"next_batch_index": 212, "optimizer_updates": 50}

    checkpoint = _load_checkpoint("checkpoint-progress.pt", FakeTorch)
    assert FakeTorch.call == (
        "checkpoint-progress.pt",
        {"map_location": "cpu", "weights_only": False},
    )
    assert checkpoint == {"next_batch_index": 212, "optimizer_updates": 50}


def test_resume_restores_rng_before_loading_model_or_optimizer_state():
    source = inspect.getsource(train)
    resume_block = source.split("if resume:", 1)[1].split("else:", 1)[0]
    assert resume_block.index("_restore_rng_state") < resume_block.index("model.load_state_dict")
    assert resume_block.index("_restore_rng_state") < resume_block.index("optimizer.load_state_dict")


def test_rng_tensor_normalization_converts_legacy_cuda_state_to_cpu_byte():
    class FakeTensor:
        def detach(self):
            return self

        def to(self, *, device, dtype):
            self.device, self.dtype = device, dtype
            return self

        def contiguous(self):
            self.is_contiguous = True
            return self

    class FakeTorch:
        uint8 = "uint8"

        @staticmethod
        def is_tensor(value):
            return True

    tensor = _cpu_byte_rng_state(FakeTensor(), FakeTorch)
    assert tensor.device == "cpu"
    assert tensor.dtype == "uint8"
    assert tensor.is_contiguous


@pytest.mark.parametrize(
    ("dataset_size", "batch_size", "accumulation", "expected_batches", "expected_steps"),
    [
        (16, 4, 2, 4, 2),
        (17, 4, 2, 5, 3),
        (3, 4, 4, 1, 1),
    ],
)
def test_training_schedule_is_computed_before_loader_construction(
    dataset_size, batch_size, accumulation, expected_batches, expected_steps,
):
    batches, steps, total = _training_step_counts(
        dataset_size=dataset_size,
        batch_size=batch_size,
        accumulation=accumulation,
        max_epochs=5,
    )
    assert batches == expected_batches
    assert steps == expected_steps
    assert total == expected_steps * 5


def test_scheduler_setup_never_reads_epoch_local_train_loader():
    setup_source = inspect.getsource(train).split("for epoch in range", 1)[0]
    assert "_training_step_counts(" in setup_source
    assert "len(train_loader)" not in setup_source


def test_epoch_loader_seed_and_diagnostic_worker_override_remain_stable():
    assert _epoch_loader_runtime(
        seed=1729, epoch=3, runtime_workers=2,
        diagnostic_mode=False, diagnostic_num_workers=0,
    ) == (1732, 2)
    assert _epoch_loader_runtime(
        seed=1729, epoch=3, runtime_workers=2,
        diagnostic_mode=True, diagnostic_num_workers=0,
    ) == (1732, 0)
    assert _epoch_loader_runtime(
        seed=1729, epoch=3, runtime_workers=2,
        diagnostic_mode=True, diagnostic_num_workers=4,
    ) == (1732, 4)


def test_diagnostic_cli_bounds_first_batches_without_unlocking_training():
    args = parse_args([
        "--config", "c", "--adapter-root", "a", "--initialization", "w",
        "--output", "o", "--diagnostic-max-batches", "50",
        "--diagnostic-num-workers", "2",
    ])
    assert args.diagnostic_max_batches == 50
    assert args.diagnostic_num_workers == 2
    assert args.authorize_training is False


def test_frozen_task7_config_is_bounded_and_test_locked():
    config_path = (
        Path(__file__).parents[1] / "ml/training/configs" /
        "swiss_dwellings_rooms_maskrcnn_task7_bounded_v1.json"
    )
    config = json.loads(config_path.read_text())
    assert config["status"] == "FROZEN_NOT_STARTED"
    assert config["dataset"]["splits"] == {"train": 11337, "val": 1362, "test": 1203}
    assert config["dataset"]["test_policy"] == "LOCKED_UNTOUCHED_UNTIL_FINAL_EVALUATION"
    assert config["training"]["max_epochs"] == 12
    assert config["training"]["batch_size_per_gpu"] == 1
    assert config["evaluation"]["selection_metric"] == "val_mask_map_50_95"
    assert config["runtime"]["numpy"] == "2.0.2"
    assert config["runtime"]["pycocotools"] == "2.0.10"
    assert len(config["taxonomy"]) == 14


def test_kaggle_notebook_pins_numpy2_and_requires_restart_before_imports():
    notebook_path = (
        Path(__file__).parents[1] / "ml/notebooks" /
        "maskrcnn_task7_bounded_training.ipynb"
    )
    notebook = json.loads(notebook_path.read_text())
    install_cell = "".join(notebook["cells"][1]["source"])
    import_cell = "".join(notebook["cells"][2]["source"])
    final_cell = "".join(notebook["cells"][-1]["source"])
    artifact_cell = "".join(notebook["cells"][3]["source"])
    validation_cell = "".join(notebook["cells"][4]["source"])
    assert "numpy==2.0.2" in install_cell
    assert "numpy==1.26.4" not in install_cell
    assert "restart the Kaggle session" in install_cell
    assert "BINARY COMPATIBILITY: PASS" in import_cell
    assert "coco_mask.decode" in import_cell and "torch.from_numpy" in import_cell
    assert "resolve_archive_or_directory" in artifact_cell
    assert "extracted_tree_sha256" in artifact_cell
    assert "training_lock_path" in artifact_cell
    assert "evidence == training_lock['validation']" in validation_cell
    assert "AUTHORIZE_GPU_TRAINING = False" in final_cell
