"""Reliable Kaggle operations for the frozen Task 7 Mask R-CNN run.

This module coordinates the existing trainer; it does not change its model,
data, split, or evaluation contracts. All mutable operational state belongs in
the Kaggle working directory, never in the input datasets.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


CHECKPOINT_NAMES = ("checkpoint-progress.pt", "checkpoint-latest.pt", "checkpoint-best.pt")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        os.replace(temporary, path)
    except PermissionError:
        # Windows sandbox/AV filters can deny same-directory atomic rename.
        # Kaggle/Linux always takes the atomic path above.
        if os.name != "nt":
            raise
        path.write_text(temporary.read_text(encoding="utf-8"), encoding="utf-8")
        temporary.unlink(missing_ok=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class CheckpointPosition:
    run_id: str
    epoch: int
    next_batch_index: int
    optimizer_updates: int
    epoch_complete: bool

    @classmethod
    def from_payload(cls, payload: dict) -> "CheckpointPosition":
        return cls(
            run_id=str(payload["run_id"]),
            epoch=int(payload["epoch"]),
            next_batch_index=int(payload.get("next_batch_index", 0)),
            optimizer_updates=int(payload.get("optimizer_updates", 0)),
            epoch_complete=bool(payload.get("epoch_complete", True)),
        )


def _position_key(position: CheckpointPosition) -> tuple[int, int, int]:
    completed_epoch = position.epoch + int(position.epoch_complete)
    batch = 0 if position.epoch_complete else position.next_batch_index
    return position.optimizer_updates, completed_epoch, batch


def compare_positions(candidate: CheckpointPosition, reference: CheckpointPosition) -> int:
    if candidate.run_id != reference.run_id:
        raise ValueError("checkpoint run_id mismatch")
    return (_position_key(candidate) > _position_key(reference)) - (
        _position_key(candidate) < _position_key(reference)
    )


def load_checkpoint_metadata(path: str | Path, *, loader: Callable | None = None) -> CheckpointPosition:
    if loader is None:
        import torch

        loader = lambda value: torch.load(value, map_location="cpu", weights_only=False)
    return CheckpointPosition.from_payload(loader(Path(path)))


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


class RunLock:
    """Atomic single-launch guard with conservative stale-lock recovery."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.token = uuid.uuid4().hex

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"pid": os.getpid(), "token": self.token, "created_at": _utc_now()}
        for _ in range(2):
            try:
                descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    current = json.loads(self.path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    raise RuntimeError(f"training lock is unreadable: {self.path}")
                if _pid_alive(int(current.get("pid", -1))):
                    raise RuntimeError(f"training already running with pid {current['pid']}")
                self.path.unlink()
                continue
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, sort_keys=True)
            return
        raise RuntimeError(f"could not acquire training lock: {self.path}")

    def release(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if payload.get("token") == self.token:
            self.path.unlink()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *_):
        self.release()


def _newest_known_position(output: Path, backup_state: Path | None, *, loader=None):
    values: list[tuple[CheckpointPosition, str]] = []
    for name in CHECKPOINT_NAMES:
        path = output / name
        if path.is_file():
            values.append((load_checkpoint_metadata(path, loader=loader), str(path)))
    if backup_state and backup_state.is_file():
        payload = json.loads(backup_state.read_text(encoding="utf-8"))
        values.append((CheckpointPosition.from_payload(payload["checkpoint"]), str(backup_state)))
    return max(values, key=lambda item: _position_key(item[0])) if values else None


def assert_resume_is_current(
    resume: str | Path, output: str | Path, config: str | Path,
    backup_state: str | Path | None = None, *, loader=None,
    remote_reference: CheckpointPosition | None = None,
) -> CheckpointPosition:
    config_payload = json.loads(Path(config).read_text(encoding="utf-8"))
    candidate = load_checkpoint_metadata(resume, loader=loader)
    if candidate.run_id != config_payload["run_id"]:
        raise ValueError("resume checkpoint belongs to another run")
    known = _newest_known_position(
        Path(output), Path(backup_state) if backup_state else None, loader=loader,
    )
    if known and compare_positions(candidate, known[0]) < 0:
        raise ValueError(f"resume checkpoint is older than {known[1]}")
    if remote_reference and compare_positions(candidate, remote_reference) < 0:
        raise ValueError("resume checkpoint is older than remote durable dataset")
    return candidate


def _tee_output(stream, log_handle) -> None:
    for raw_line in iter(stream.readline, ""):
        line = raw_line.rstrip("\n")
        print(line, flush=True)
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            event = {"event": "trainer_output", "message": line}
        if not isinstance(event, dict):
            event = {"event": "trainer_output", "message": line}
        event["observed_at_utc"] = _utc_now()
        log_handle.write(json.dumps(event, sort_keys=True) + "\n")
        log_handle.flush()


def launch_training(args) -> int:
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    stop_file = output / "STOP_REQUESTED"
    stop_file.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix="task7-remote-head-", dir=output) as directory:
        remote_reference = _download_remote_position(
            args.remote_dataset, Path(directory),
            retries=args.remote_check_retries,
        )
    position = assert_resume_is_current(
        args.resume, output, args.config, args.backup_state,
        remote_reference=remote_reference,
    )
    command = [
        sys.executable, "-m", "ml.training.maskrcnn_task7_train",
        "--config", args.config,
        "--adapter-root", args.adapter_root,
        "--initialization", args.initialization,
        "--output", args.output,
        "--resume", args.resume,
        "--authorize-training",
        "--num-workers", str(args.num_workers),
        "--heartbeat-every-batches", str(args.heartbeat_every_batches),
        "--checkpoint-every-optimizer-updates", str(args.checkpoint_every_optimizer_updates),
        "--stop-file", str(stop_file),
    ]
    log_path = output / "training-events.jsonl"
    lock_path = output / "training.lock"
    state_path = output / "training-process.json"
    with RunLock(lock_path):
        with log_path.open("a", encoding="utf-8", buffering=1) as log_handle:
            process = subprocess.Popen(
                command, cwd=args.backend, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, bufsize=1,
            )
            _atomic_json(state_path, {
                "pid": process.pid, "started_at": _utc_now(),
                "resume": str(Path(args.resume).resolve()),
                "resume_position": asdict(position), "command": command,
            })

            stop_signals = {signal.SIGINT, signal.SIGTERM}
            previous_handlers = {}

            def request_safe_stop(signum, _frame):
                stop_file.touch(exist_ok=True)
                print(f"safe stop requested by signal {signum}; waiting for optimizer boundary", flush=True)

            for sig in stop_signals:
                previous_handlers[sig] = signal.getsignal(sig)
                signal.signal(sig, request_safe_stop)
            try:
                _tee_output(process.stdout, log_handle)
                return process.wait()
            finally:
                for sig, handler in previous_handlers.items():
                    signal.signal(sig, handler)
                _atomic_json(state_path, {
                    "pid": process.pid, "started_at": json.loads(
                        state_path.read_text(encoding="utf-8")
                    )["started_at"],
                    "completed_at": _utc_now(), "exit_code": process.poll(),
                    "resume": str(Path(args.resume).resolve()),
                    "resume_position": asdict(position), "command": command,
                })


def request_stop(output: str | Path) -> Path:
    marker = Path(output) / "STOP_REQUESTED"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch(exist_ok=True)
    return marker


def _json_events(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    events = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def training_status(
    output: str | Path, *, config: str | Path | None = None,
    backup_state: str | Path | None = None, now: float | None = None,
    checkpoint_loader=None,
) -> dict:
    output = Path(output)
    events = _json_events(output / "training-events.jsonl")
    heartbeats = [event for event in events if event.get("event") == "training_heartbeat"]
    latest = heartbeats[-1] if heartbeats else next((event for event in reversed(events) if "batch" in event), {})
    speed = eta = None
    if len(heartbeats) >= 2:
        first, last = heartbeats[-2:]
        batches = int(last["batch"]) - int(first["batch"])
        elapsed = (
            datetime.fromisoformat(last["observed_at_utc"]).timestamp()
            - datetime.fromisoformat(first["observed_at_utc"]).timestamp()
        )
        if batches > 0 and elapsed > 0:
            speed = batches / elapsed
            max_epochs = 1
            if config:
                max_epochs = int(json.loads(Path(config).read_text(encoding="utf-8"))["training"]["max_epochs"])
            remaining = max(0, int(last["batches_in_epoch"]) - int(last["batch"]))
            remaining += max(0, max_epochs - int(last["epoch"])) * int(last["batches_in_epoch"])
            eta = remaining / speed
    checkpoint_path = output / "checkpoint-progress.pt"
    checkpoint = None
    checkpoint_age = None
    if checkpoint_path.is_file():
        checkpoint = asdict(load_checkpoint_metadata(checkpoint_path, loader=checkpoint_loader))
        checkpoint_age = (now if now is not None else time.time()) - checkpoint_path.stat().st_mtime
    backup = None
    if backup_state and Path(backup_state).is_file():
        backup = json.loads(Path(backup_state).read_text(encoding="utf-8"))
    lock_path = output / "training.lock"
    running = False
    if lock_path.is_file():
        try:
            running = _pid_alive(int(json.loads(lock_path.read_text(encoding="utf-8"))["pid"]))
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            running = False
    backup_error_path = (
        Path(backup_state).with_suffix(".error.json") if backup_state else None
    )
    backup_error = None
    if backup_error_path and backup_error_path.is_file():
        backup_error = json.loads(backup_error_path.read_text(encoding="utf-8"))
    return {
        "status": "running" if running else "not_running",
        "epoch": latest.get("epoch"), "batch": latest.get("batch"),
        "batches_in_epoch": latest.get("batches_in_epoch"),
        "optimizer_updates": latest.get("optimizer_updates"),
        "batches_per_second": speed, "eta_seconds": eta,
        "checkpoint": checkpoint, "checkpoint_age_seconds": checkpoint_age,
        "backup": backup, "backup_error": backup_error,
    }


def _run_with_retry(command: list[str], *, retries: int, runner=subprocess.run) -> None:
    error = None
    for attempt in range(1, retries + 1):
        try:
            runner(command, check=True, capture_output=True, text=True)
            return
        except subprocess.CalledProcessError as exc:
            error = exc
            if attempt < retries:
                time.sleep(min(30, 2 ** (attempt - 1)))
    raise RuntimeError(f"command failed after {retries} attempts: {command}") from error


def _find_downloaded(path: Path, filename: str) -> Path:
    matches = list(path.rglob(filename))
    if len(matches) != 1:
        raise RuntimeError(f"expected one downloaded {filename}, found {len(matches)}")
    return matches[0]


def _download_remote_position(
    dataset: str, destination: Path, *, retries: int,
    runner=subprocess.run, loader=None,
) -> CheckpointPosition:
    """Read the durable dataset head before allowing a new publication.

    New-format datasets expose compact metadata. Existing Task 7 datasets that
    predate this tool remain supported by inspecting their checkpoint on CPU.
    """
    metadata_dir = destination / "remote-metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    try:
        _run_with_retry([
            "kaggle", "datasets", "download", "-d", dataset,
            "-f", "checkpoint-metadata.json", "-p", str(metadata_dir),
            "--force", "--unzip",
        ], retries=retries, runner=runner)
        metadata_path = _find_downloaded(metadata_dir, "checkpoint-metadata.json")
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        return CheckpointPosition.from_payload(payload["checkpoint"])
    except (RuntimeError, FileNotFoundError):
        legacy_dir = destination / "remote-legacy"
        legacy_dir.mkdir(parents=True, exist_ok=True)
        _run_with_retry([
            "kaggle", "datasets", "download", "-d", dataset,
            "-f", "checkpoint-progress.pt", "-p", str(legacy_dir),
            "--force", "--unzip",
        ], retries=retries, runner=runner)
        return load_checkpoint_metadata(
            _find_downloaded(legacy_dir, "checkpoint-progress.pt"), loader=loader,
        )


def publish_checkpoint(
    checkpoint: str | Path, *, dataset: str, state_path: str | Path,
    retries: int = 3, runner=subprocess.run, loader=None,
) -> dict:
    checkpoint = Path(checkpoint)
    state_path = Path(state_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="task7-checkpoint-", dir=state_path.parent,
    ) as directory:
        stage = Path(directory) / "stage"
        verify = Path(directory) / "verify"
        stage.mkdir()
        verify.mkdir()
        shutil.copy2(checkpoint, stage / "checkpoint-progress.pt")
        snapshot = stage / "checkpoint-progress.pt"
        candidate = load_checkpoint_metadata(snapshot, loader=loader)
        sha256 = _sha256(snapshot)
        references = []
        local_verified = None
        if state_path.is_file():
            local_verified = json.loads(state_path.read_text(encoding="utf-8"))
            references.append((
                CheckpointPosition.from_payload(
                    local_verified["checkpoint"]
                ),
                "local verified backup state",
            ))
        for previous, source in references:
            if compare_positions(candidate, previous) < 0:
                raise ValueError(f"checkpoint regression refused against {source}")
        if (
            local_verified
            and local_verified.get("status") == "verified"
            and local_verified.get("sha256") == sha256
            and compare_positions(candidate, references[0][0]) == 0
        ):
            return {**local_verified, "reused_verified_backup": True}
        references.append((
            _download_remote_position(
                dataset, Path(directory), retries=retries,
                runner=runner, loader=loader,
            ),
            "remote durable dataset",
        ))
        previous, source = references[-1]
        if compare_positions(candidate, previous) < 0:
            raise ValueError(f"checkpoint regression refused against {source}")
        metadata = {
            "schema_version": 1, "dataset": dataset,
            "checkpoint": asdict(candidate), "sha256": sha256,
            "published_at": _utc_now(),
        }
        _atomic_json(stage / "checkpoint-metadata.json", metadata)
        _atomic_json(stage / "dataset-metadata.json", {
            "id": dataset, "title": dataset.split("/", 1)[-1],
            "licenses": [{"name": "other"}],
        })
        _run_with_retry([
            "kaggle", "datasets", "version", "-p", str(stage),
            "-m", f"Task 7 checkpoint optimizer_updates={candidate.optimizer_updates}",
            "--dir-mode", "zip",
        ], retries=retries, runner=runner)
        remote_sha = None
        for attempt in range(1, retries + 1):
            shutil.rmtree(verify, ignore_errors=True)
            verify.mkdir()
            _run_with_retry([
                "kaggle", "datasets", "download", "-d", dataset,
                "-f", "checkpoint-progress.pt", "-p", str(verify),
                "--force", "--unzip",
            ], retries=1, runner=runner)
            remote = _find_downloaded(verify, "checkpoint-progress.pt")
            remote_sha = _sha256(remote)
            if remote_sha == sha256:
                break
            if attempt < retries:
                time.sleep(min(30, 2 ** (attempt - 1)))
        if remote_sha != sha256:
            raise RuntimeError("remote checkpoint SHA-256 verification failed")
    metadata["remote_sha256"] = remote_sha
    metadata["status"] = "verified"
    _atomic_json(state_path, metadata)
    return metadata


def backup_worker(args) -> int:
    checkpoint = Path(args.checkpoint)
    last_signature = None
    while True:
        if checkpoint.is_file():
            signature = (checkpoint.stat().st_size, checkpoint.stat().st_mtime_ns)
            if signature != last_signature:
                try:
                    result = publish_checkpoint(
                        checkpoint, dataset=args.dataset, state_path=args.state,
                        retries=args.retries,
                    )
                except Exception as exc:
                    error_path = Path(args.state).with_suffix(".error.json")
                    _atomic_json(error_path, {
                        "event": "checkpoint_backup_failed",
                        "failed_at": _utc_now(), "error": str(exc),
                    })
                    print(json.dumps({
                        "event": "checkpoint_backup_failed", "error": str(exc),
                    }, sort_keys=True), flush=True)
                    if args.once:
                        raise
                else:
                    Path(args.state).with_suffix(".error.json").unlink(missing_ok=True)
                    print(json.dumps({"event": "checkpoint_backup_verified", **result}, sort_keys=True), flush=True)
                    last_signature = signature
        if args.once:
            return 0
        time.sleep(args.poll_seconds)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    launch = subparsers.add_parser("launch")
    for name in ("backend", "config", "adapter-root", "initialization", "output", "resume"):
        launch.add_argument(f"--{name}", required=True)
    launch.add_argument("--backup-state")
    launch.add_argument("--remote-dataset", required=True)
    launch.add_argument("--remote-check-retries", type=int, default=3)
    launch.add_argument("--num-workers", type=int, default=0)
    launch.add_argument("--heartbeat-every-batches", type=int, default=10)
    launch.add_argument("--checkpoint-every-optimizer-updates", type=int, default=50)

    status = subparsers.add_parser("status")
    status.add_argument("--output", required=True)
    status.add_argument("--config")
    status.add_argument("--backup-state")

    stop = subparsers.add_parser("stop")
    stop.add_argument("--output", required=True)

    backup = subparsers.add_parser("backup")
    backup.add_argument("--checkpoint", required=True)
    backup.add_argument("--dataset", required=True)
    backup.add_argument("--state", required=True)
    backup.add_argument("--retries", type=int, default=3)
    backup.add_argument("--poll-seconds", type=int, default=60)
    backup.add_argument("--once", action="store_true")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.command == "launch":
        return launch_training(args)
    if args.command == "status":
        print(json.dumps(training_status(
            args.output, config=args.config, backup_state=args.backup_state,
        ), indent=2, sort_keys=True))
        return 0
    if args.command == "stop":
        print(request_stop(args.output))
        return 0
    if args.command == "backup":
        return backup_worker(args)
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
