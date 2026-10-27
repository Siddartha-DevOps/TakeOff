import json
import hashlib
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from ml.training import maskrcnn_task7_ops as ops


def checkpoint(run_id="run", epoch=0, batch=100, updates=25, complete=False):
    return {
        "run_id": run_id, "epoch": epoch, "next_batch_index": batch,
        "optimizer_updates": updates, "epoch_complete": complete,
    }


def resumable_checkpoint(*, batch=1216, updates=301, skipped=3):
    payload = checkpoint(batch=batch, updates=updates)
    payload.update({
        "model": {"weight": "present"},
        "optimizer": {"state": {}, "param_groups": [{"lr": 0.0001}]},
        "scheduler": {"last_epoch": updates},
        "scaler": {"scale": 8192.0},
        "rng_state": {
            "python": (3, (), None), "numpy": ("MT19937",),
            "torch_cpu": b"cpu", "torch_cuda": [b"cuda"],
        },
        "optimizer_attempts": updates + skipped,
        "skipped_optimizer_updates": skipped,
    })
    return payload


def task7_config(path):
    path.write_text(json.dumps({
        "run_id": "run",
        "runtime": {"seed": 42, "mixed_precision": True},
        "dataset": {"splits": {"train": 11337}},
        "training": {
            "batch_size_per_gpu": 1, "gradient_accumulation_steps": 4,
        },
    }))
    return path


def test_checkpoint_order_and_regression_protection(tmp_path, monkeypatch):
    source = tmp_path / "checkpoint.pt"
    source.write_bytes(b"new")
    state = tmp_path / "backup.json"
    state.write_text(json.dumps({"checkpoint": checkpoint(batch=412, updates=100)}))

    with pytest.raises(ValueError, match="regression refused"):
        ops.publish_checkpoint(
            source, dataset="owner/data", state_path=state,
            loader=lambda _: checkpoint(batch=212, updates=50),
        )


def test_equal_or_newer_checkpoint_order_is_allowed():
    old = ops.CheckpointPosition.from_payload(checkpoint(batch=412, updates=100))
    equal = ops.CheckpointPosition.from_payload(checkpoint(batch=412, updates=100))
    newer = ops.CheckpointPosition.from_payload(checkpoint(batch=612, updates=150))
    assert ops.compare_positions(equal, old) == 0
    assert ops.compare_positions(newer, old) > 0


def test_resume_refuses_older_local_or_verified_backup(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"run_id": "run"}))
    output = tmp_path / "output"
    output.mkdir()
    resume = tmp_path / "resume.pt"
    resume.touch()
    latest = output / "checkpoint-progress.pt"
    latest.touch()
    payloads = {
        resume: checkpoint(batch=212, updates=50),
        latest: checkpoint(batch=612, updates=150),
    }
    with pytest.raises(ValueError, match="older"):
        ops.assert_resume_is_current(
            resume, output, config, loader=lambda path: payloads[Path(path)],
        )


def test_resume_requires_matching_run_id(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"run_id": "expected"}))
    resume = tmp_path / "resume.pt"
    resume.touch()
    with pytest.raises(ValueError, match="another run"):
        ops.assert_resume_is_current(
            resume, tmp_path / "out", config,
            loader=lambda _: checkpoint(run_id="wrong"),
        )


def test_full_resume_preflight_reconciles_state_and_next_batch(tmp_path):
    resume = tmp_path / "checkpoint-progress.pt"
    resume.write_bytes(b"immutable-checkpoint")
    sha256 = hashlib.sha256(resume.read_bytes()).hexdigest()
    config = task7_config(tmp_path / "config.json")
    payload = resumable_checkpoint()

    report = ops.validate_resume_checkpoint(
        resume, tmp_path / "output", config, expected_sha256=sha256,
        loader=lambda _path: payload,
    )

    assert report["status"] == "PASS"
    assert report["position"] == {
        "run_id": "run", "epoch": 0, "next_batch_index": 1216,
        "optimizer_updates": 301, "epoch_complete": False,
    }
    assert report["optimizer_attempts"] == 304
    assert report["skipped_optimizer_updates"] == 3
    assert report["scheduler_last_epoch"] == 301
    assert report["next_batch_index_zero_based"] == 1216
    assert report["next_display_batch"] == 1217
    assert report["duplicate_training_batches"] == 0
    assert report["skipped_training_batches"] == 0
    assert all(report["restorable_state"].values())


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda row: row["rng_state"].pop("torch_cpu"), "missing torch_cpu"),
        (lambda row: row["scheduler"].update(last_epoch=509), "scheduler last_epoch"),
        (lambda row: row.update(next_batch_index=2051), "optimizer boundary"),
        (lambda row: row.update(optimizer_attempts=512), "cursor-derived"),
    ],
)
def test_resume_preflight_rejects_incomplete_or_inconsistent_state(
    tmp_path, mutation, message,
):
    resume = tmp_path / "checkpoint-progress.pt"
    resume.write_bytes(b"immutable-checkpoint")
    sha256 = hashlib.sha256(resume.read_bytes()).hexdigest()
    payload = resumable_checkpoint()
    mutation(payload)
    with pytest.raises(ValueError, match=message):
        ops.validate_resume_checkpoint(
            resume, tmp_path / "output", task7_config(tmp_path / "config.json"),
            expected_sha256=sha256, loader=lambda _path: payload,
        )


def test_resume_preflight_refuses_checkpoint_hash_mismatch(tmp_path):
    resume = tmp_path / "checkpoint-progress.pt"
    resume.write_bytes(b"immutable-checkpoint")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        ops.validate_resume_checkpoint(
            resume, tmp_path / "output", task7_config(tmp_path / "config.json"),
            expected_sha256="0" * 64, loader=lambda _path: resumable_checkpoint(),
        )


def test_resume_refuses_checkpoint_older_than_remote_durable_head(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"run_id": "run"}))
    resume = tmp_path / "resume.pt"
    resume.touch()
    remote = ops.CheckpointPosition.from_payload(checkpoint(batch=612, updates=150))
    with pytest.raises(ValueError, match="remote durable"):
        ops.assert_resume_is_current(
            resume, tmp_path / "out", config,
            loader=lambda _: checkpoint(batch=412, updates=100),
            remote_reference=remote,
        )


def test_run_lock_prevents_duplicate_launcher(tmp_path, monkeypatch):
    monkeypatch.setattr(ops, "_pid_alive", lambda _pid: True)
    first = ops.RunLock(tmp_path / "training.lock")
    first.acquire()
    try:
        with pytest.raises(RuntimeError, match="already running"):
            ops.RunLock(first.path).acquire()
    finally:
        first.release()


def test_safe_interruption_marker_and_trainer_boundary_contract(tmp_path):
    marker = ops.request_stop(tmp_path)
    assert marker.name == "STOP_REQUESTED" and marker.is_file()
    source = (
        Path(__file__).parents[1] / "ml" / "training" / "maskrcnn_task7_train.py"
    ).read_text(encoding="utf-8")
    stop_check = source.index("_should_stop_at_boundary(", source.index("for batch_index"))
    checkpoint_save = source.index("interrupted_checkpoint_complete", stop_check)
    assert checkpoint_save > stop_check
    assert "epoch_complete=False" in source[stop_check:checkpoint_save]

    from ml.training.maskrcnn_task7_train import _should_stop_at_boundary
    assert not _should_stop_at_boundary(stop_file=marker, optimizer_boundary=False)
    assert _should_stop_at_boundary(stop_file=marker, optimizer_boundary=True)


def test_remote_backup_retries_and_verifies_downloaded_sha(tmp_path, monkeypatch):
    source = tmp_path / "checkpoint.pt"
    source.write_bytes(b"checkpoint-bytes")
    state = tmp_path / "backup-state.json"
    calls = []

    def runner(command, **_kwargs):
        calls.append(command)
        if len(calls) == 1:
            raise subprocess.CalledProcessError(1, command, stderr="temporary")
        if "download" in command:
            destination = Path(command[command.index("-p") + 1])
            destination.mkdir(parents=True, exist_ok=True)
            if "checkpoint-metadata.json" in command:
                (destination / "checkpoint-metadata.json").write_text(json.dumps({
                    "checkpoint": checkpoint(batch=612, updates=150),
                }))
            else:
                (destination / "checkpoint-progress.pt").write_bytes(source.read_bytes())
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(ops.time, "sleep", lambda _seconds: None)
    result = ops.publish_checkpoint(
        source, dataset="owner/data", state_path=state, retries=2,
        runner=runner, loader=lambda _: checkpoint(batch=612, updates=150),
    )
    assert result["status"] == "verified"
    assert result["sha256"] == result["remote_sha256"]
    assert len(calls) == 4


def test_remote_backup_failure_does_not_advance_state(tmp_path, monkeypatch):
    source = tmp_path / "checkpoint.pt"
    source.write_bytes(b"checkpoint")
    state = tmp_path / "backup-state.json"

    def fail(command, **_kwargs):
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(ops.time, "sleep", lambda _seconds: None)
    with pytest.raises(RuntimeError, match="after 2 attempts"):
        ops.publish_checkpoint(
            source, dataset="owner/data", state_path=state, retries=2,
            runner=fail, loader=lambda _: checkpoint(),
        )
    assert not state.exists()


def test_continuous_backup_worker_records_failure_and_retries_later(tmp_path, monkeypatch):
    checkpoint_path = tmp_path / "checkpoint.pt"
    checkpoint_path.write_bytes(b"checkpoint")
    state = tmp_path / "state.json"
    attempts = 0

    def publish(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary remote failure")
        return {"status": "verified"}

    def stop_after_retry(_seconds):
        if attempts >= 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(ops, "publish_checkpoint", publish)
    monkeypatch.setattr(ops.time, "sleep", stop_after_retry)
    args = SimpleNamespace(
        checkpoint=str(checkpoint_path), dataset="owner/data",
        state=str(state), retries=1, poll_seconds=0, once=False,
    )
    with pytest.raises(KeyboardInterrupt):
        ops.backup_worker(args)
    assert attempts == 2


def test_remote_head_prevents_regression_without_local_state(tmp_path, monkeypatch):
    source = tmp_path / "checkpoint.pt"
    source.write_bytes(b"older")
    state = tmp_path / "backup-state.json"

    def runner(command, **_kwargs):
        destination = Path(command[command.index("-p") + 1])
        destination.mkdir(parents=True, exist_ok=True)
        if "checkpoint-metadata.json" in command:
            (destination / "checkpoint-metadata.json").write_text(json.dumps({
                "checkpoint": checkpoint(batch=612, updates=150),
            }))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    with pytest.raises(ValueError, match="remote durable dataset"):
        ops.publish_checkpoint(
            source, dataset="owner/data", state_path=state, retries=1,
            runner=runner, loader=lambda _: checkpoint(batch=412, updates=100),
        )
    assert not state.exists()


def test_identical_verified_checkpoint_is_not_republished(tmp_path):
    source = tmp_path / "checkpoint.pt"
    source.write_bytes(b"same")
    position = checkpoint(batch=612, updates=150)
    state = tmp_path / "backup-state.json"
    state.write_text(json.dumps({
        "status": "verified", "checkpoint": position,
        "sha256": ops._sha256(source), "remote_sha256": ops._sha256(source),
    }))

    def must_not_run(*_args, **_kwargs):
        raise AssertionError("verified checkpoint was republished")

    result = ops.publish_checkpoint(
        source, dataset="owner/data", state_path=state,
        runner=must_not_run, loader=lambda _: position,
    )
    assert result["reused_verified_backup"] is True


def test_status_reports_speed_eta_checkpoint_age_and_backup(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    log = output / "training-events.jsonl"
    log.write_text("\n".join([
        json.dumps({
            "event": "training_heartbeat", "epoch": 1, "batch": 600,
            "batches_in_epoch": 1000, "optimizer_updates": 149,
            "observed_at_utc": "2026-10-10T00:00:00+00:00",
        }),
        json.dumps({
            "event": "training_heartbeat", "epoch": 1, "batch": 620,
            "batches_in_epoch": 1000, "optimizer_updates": 154,
            "observed_at_utc": "2026-10-10T00:00:10+00:00",
        }),
    ]))
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"training": {"max_epochs": 2}}))
    checkpoint_path = output / "checkpoint-progress.pt"
    checkpoint_path.touch()
    backup = tmp_path / "backup.json"
    backup.write_text(json.dumps({"status": "verified"}))
    status = ops.training_status(
        output, config=config, backup_state=backup,
        now=checkpoint_path.stat().st_mtime + 30,
        checkpoint_loader=lambda _: checkpoint(batch=612, updates=150),
    )
    assert status["batch"] == 620
    assert status["optimizer_updates"] == 154
    assert status["batches_per_second"] == 2.0
    assert status["eta_seconds"] == 690.0
    assert status["checkpoint_age_seconds"] == 30
    assert status["backup"]["status"] == "verified"
