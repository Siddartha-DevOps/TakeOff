"""Bounded, resumable Task 7 Mask R-CNN training entry point.

The command defaults to validation only. Real training requires the explicit
``--authorize-training`` switch so package preparation cannot launch a run.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import time
from pathlib import Path

from ml.training.maskrcnn_task7_package import validate_package


PROGRESS_INTERVAL_OPTIMIZER_ATTEMPTS = 100
HEARTBEAT_INTERVAL_BATCHES = 10


def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--adapter-root", required=True)
    parser.add_argument("--initialization", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--authorize-training", action="store_true")
    parser.add_argument("--resume")
    parser.add_argument("--diagnostic-max-batches", type=int)
    parser.add_argument("--diagnostic-num-workers", type=int, default=0)
    parser.add_argument("--num-workers", type=int, default=0)
    parser.add_argument("--heartbeat-every-batches", type=int, default=HEARTBEAT_INTERVAL_BATCHES)
    parser.add_argument("--checkpoint-every-optimizer-updates", type=int, default=50)
    return parser.parse_args(argv)


def _seed_everything(seed: int, deterministic: bool) -> None:
    import numpy as np
    import torch

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.benchmark = False
    torch.use_deterministic_algorithms(deterministic, warn_only=True)


class _FlipDataset:
    def __init__(self, source, horizontal: float, vertical: float, seed: int):
        self.source, self.horizontal, self.vertical, self.seed = source, horizontal, vertical, seed
        self.epoch = 0

    def __len__(self):
        return len(self.source)

    def set_epoch(self, epoch: int):
        self.epoch = epoch

    def __getitem__(self, index):
        import torch

        image, target = self.source[index]
        generator = random.Random(self.seed + self.epoch * len(self) + index)
        height, width = image.shape[-2:]
        if generator.random() < self.horizontal:
            image = torch.flip(image, (-1,))
            target["masks"] = torch.flip(target["masks"], (-1,))
            boxes = target["boxes"].clone()
            boxes[:, 0], boxes[:, 2] = width - target["boxes"][:, 2], width - target["boxes"][:, 0]
            target["boxes"] = boxes
        if generator.random() < self.vertical:
            image = torch.flip(image, (-2,))
            target["masks"] = torch.flip(target["masks"], (-2,))
            boxes = target["boxes"].clone()
            boxes[:, 1], boxes[:, 3] = height - target["boxes"][:, 3], height - target["boxes"][:, 1]
            target["boxes"] = boxes
        return image, target


def _save_checkpoint(
    path, *, model, optimizer, scheduler, scaler, epoch, best_metric,
    stale_epochs, optimizer_attempts, optimizer_updates, skipped_optimizer_updates,
    config, epoch_complete=True, next_batch_index=0, epoch_running_loss=0.0,
):
    import torch

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    torch.save({
        "model": model.state_dict(), "optimizer": optimizer.state_dict(),
        "scheduler": scheduler.state_dict(), "scaler": scaler.state_dict(),
        "epoch": epoch, "best_metric": best_metric, "stale_epochs": stale_epochs,
        "optimizer_attempts": optimizer_attempts,
        "optimizer_updates": optimizer_updates,
        "skipped_optimizer_updates": skipped_optimizer_updates,
        "epoch_complete": epoch_complete,
        "next_batch_index": next_batch_index,
        "epoch_running_loss": epoch_running_loss,
        "rng_state": _capture_rng_state(torch),
        "run_id": config["run_id"],
    }, temporary)
    os.replace(temporary, path)


def _capture_rng_state(torch) -> dict:
    import numpy as np

    return {
        "python": random.getstate(),
        "numpy": np.random.get_state(),
        "torch_cpu": torch.get_rng_state().detach().cpu().clone(),
        "torch_cuda": [
            value.detach().cpu().clone()
            for value in (torch.cuda.get_rng_state_all() if torch.cuda.is_available() else [])
        ],
    }


def _cpu_byte_rng_state(value, torch):
    """Normalize deserialized RNG tensors to the CPU ByteTensor API contract."""
    tensor = value if torch.is_tensor(value) else torch.as_tensor(value)
    return tensor.detach().to(device="cpu", dtype=torch.uint8).contiguous()


def _restore_rng_state(state: dict | None, torch) -> bool:
    if not state:
        return False
    import numpy as np

    random.setstate(state["python"])
    np.random.set_state(state["numpy"])
    torch.set_rng_state(_cpu_byte_rng_state(state["torch_cpu"], torch))
    if state.get("torch_cuda") and torch.cuda.is_available():
        torch.cuda.set_rng_state_all([
            _cpu_byte_rng_state(value, torch) for value in state["torch_cuda"]
        ])
    return True


def _load_checkpoint(path, torch) -> dict:
    """Keep checkpoint tensors on CPU until each consumer restores its state."""
    return torch.load(path, map_location="cpu", weights_only=False)


def _step_optimizer_with_amp(*, scaler, optimizer, scheduler) -> dict:
    """Advance the scheduler only when GradScaler performs optimizer.step()."""
    scale_before = float(scaler.get_scale())
    scaler.step(optimizer)
    scaler.update()
    scale_after = float(scaler.get_scale())
    skipped = scale_after < scale_before
    if not skipped:
        scheduler.step()
    return {
        "optimizer_step_performed": not skipped,
        "grad_scale_before": scale_before,
        "grad_scale_after": scale_after,
    }


def _unscaled_loss_value(loss, accumulation: int) -> float:
    return float(loss.detach().item()) * accumulation


def _should_log_progress(*, optimizer_attempts: int, skipped: bool, final_batch: bool) -> bool:
    return (
        skipped or optimizer_attempts == 1 or final_batch or
        optimizer_attempts % PROGRESS_INTERVAL_OPTIMIZER_ATTEMPTS == 0
    )


def _training_step_counts(
    *, dataset_size: int, batch_size: int, accumulation: int, max_epochs: int,
) -> tuple[int, int, int]:
    """Return batch and optimizer-step counts without constructing a DataLoader."""
    batches_per_epoch = math.ceil(dataset_size / batch_size)
    steps_per_epoch = math.ceil(batches_per_epoch / accumulation)
    return batches_per_epoch, steps_per_epoch, steps_per_epoch * max_epochs


def _epoch_loader_runtime(
    *, seed: int, epoch: int, runtime_workers: int,
    diagnostic_mode: bool, diagnostic_num_workers: int,
) -> tuple[int, int]:
    """Return the unchanged epoch-local loader seed and worker count."""
    worker_count = diagnostic_num_workers if diagnostic_mode else runtime_workers
    return seed + epoch, worker_count


def _resume_position(checkpoint: dict) -> tuple[int, int, float]:
    if checkpoint.get("epoch_complete", True):
        return int(checkpoint["epoch"]) + 1, 0, 0.0
    return (
        int(checkpoint["epoch"]),
        int(checkpoint["next_batch_index"]),
        float(checkpoint.get("epoch_running_loss", 0.0)),
    )


def _should_checkpoint_in_epoch(*, optimizer_updates: int, interval: int) -> bool:
    return interval > 0 and optimizer_updates > 0 and optimizer_updates % interval == 0


def _should_emit_heartbeat(*, completed_batches: int, interval: int, final_batch: bool) -> bool:
    return interval > 0 and (final_batch or completed_batches % interval == 0)


def _loader_process_options(num_workers: int) -> dict:
    """Use bounded prefetch only when multiprocessing is explicitly requested."""
    if num_workers < 0:
        raise ValueError("num-workers must be non-negative")
    options = {"num_workers": num_workers, "persistent_workers": False}
    if num_workers:
        options.update({"prefetch_factor": 1, "timeout": 120})
    return options


def _rss_bytes() -> int | None:
    try:
        import psutil

        return int(psutil.Process(os.getpid()).memory_info().rss)
    except (ImportError, OSError):
        return None


def _memory_snapshot(torch, device) -> dict:
    snapshot = {"cpu_rss_bytes": _rss_bytes()}
    if device.type == "cuda":
        snapshot.update({
            "cuda_allocated_bytes": int(torch.cuda.memory_allocated(device)),
            "cuda_reserved_bytes": int(torch.cuda.memory_reserved(device)),
            "cuda_max_allocated_bytes": int(torch.cuda.max_memory_allocated(device)),
            "cuda_max_reserved_bytes": int(torch.cuda.max_memory_reserved(device)),
        })
    return snapshot


def _emit_diagnostic(event: str, *, torch, device, batch: int, metadata: list[dict], **extra) -> None:
    print(json.dumps({
        "event": event,
        "batch": batch,
        "samples": metadata,
        **_memory_snapshot(torch, device),
        **extra,
    }, sort_keys=True), flush=True)


def _evaluate(model, loader, device, score_threshold, heartbeat_every_batches=HEARTBEAT_INTERVAL_BATCHES):
    import torch
    from torchmetrics.detection.mean_ap import MeanAveragePrecision

    metric = MeanAveragePrecision(iou_type="segm", class_metrics=True)
    model.eval()
    started = time.monotonic()
    print(json.dumps({
        "event": "validation_start", "batches": len(loader),
        **_memory_snapshot(torch, device),
    }, sort_keys=True), flush=True)
    with torch.inference_mode():
        for batch_index, (images, targets) in enumerate(loader):
            outputs = model([image.to(device) for image in images])
            predictions, truths = [], []
            for output, target in zip(outputs, targets):
                keep = output["scores"] >= score_threshold
                predictions.append({
                    "boxes": output["boxes"][keep].cpu(), "scores": output["scores"][keep].cpu(),
                    "labels": output["labels"][keep].cpu(), "masks": (output["masks"][keep, 0] >= 0.5).cpu(),
                })
                truths.append({key: target[key].cpu() for key in ("boxes", "labels", "masks")})
            metric.update(predictions, truths)
            if _should_emit_heartbeat(
                completed_batches=batch_index + 1,
                interval=heartbeat_every_batches,
                final_batch=batch_index + 1 == len(loader),
            ):
                print(json.dumps({
                    "event": "validation_heartbeat", "batch": batch_index + 1,
                    "batches": len(loader),
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    **_memory_snapshot(torch, device),
                }, sort_keys=True), flush=True)
    print(json.dumps({
        "event": "validation_metric_compute_start", "batches": len(loader),
        **_memory_snapshot(torch, device),
    }, sort_keys=True), flush=True)
    result = metric.compute()
    print(json.dumps({
        "event": "validation_complete", "batches": len(loader),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        **_memory_snapshot(torch, device),
    }, sort_keys=True), flush=True)
    return {key: (value.tolist() if value.ndim else float(value)) for key, value in result.items()}


def train(
    config_path, adapter_root, initialization, output, resume=None, *,
    diagnostic_max_batches=None, diagnostic_num_workers=0,
    data_loader_num_workers=0, heartbeat_every_batches=HEARTBEAT_INTERVAL_BATCHES,
    checkpoint_every_optimizer_updates=50,
):
    import torch
    from torch.utils.data import DataLoader

    from ml.training.maskrcnn_rooms import CocoRLEMaskDataset, build_maskrcnn, collate_fn

    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    runtime, training = config["runtime"], config["training"]
    if not torch.cuda.is_available():
        raise RuntimeError("Task 7 requires a CUDA GPU")
    _seed_everything(runtime["seed"], runtime["deterministic_algorithms"])
    manifest = Path(adapter_root) / config["dataset"]["adapter_manifest_filename"]
    diagnostic_mode = diagnostic_max_batches is not None
    if diagnostic_mode and diagnostic_max_batches <= 0:
        raise ValueError("diagnostic-max-batches must be positive")
    if diagnostic_num_workers < 0 or data_loader_num_workers < 0:
        raise ValueError("data-loader worker counts must be non-negative")
    if heartbeat_every_batches <= 0:
        raise ValueError("heartbeat-every-batches must be positive")
    train_source = CocoRLEMaskDataset(
        manifest, Path(adapter_root) / "images", split="train",
        diagnostic_logging=diagnostic_mode,
    )
    val_source = CocoRLEMaskDataset(manifest, Path(adapter_root) / "images", split="val")
    augmented = _FlipDataset(
        train_source, config["augmentation"]["horizontal_flip_probability"],
        config["augmentation"]["vertical_flip_probability"], runtime["seed"],
    )
    val_loader = DataLoader(
        val_source, batch_size=1, shuffle=False, collate_fn=collate_fn,
        **_loader_process_options(data_loader_num_workers),
    )
    device = torch.device("cuda")
    model = build_maskrcnn(
        num_classes=config["architecture"]["num_classes_including_background"], pretrained=False,
        initialization_checkpoint=initialization,
        min_size=config["architecture"]["input_min_size"], max_size=config["architecture"]["input_max_size"],
    ).to(device)
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=training["learning_rate"], weight_decay=training["weight_decay"],
    )
    accumulation = training["gradient_accumulation_steps"]
    _, steps_per_epoch, total_steps = _training_step_counts(
        dataset_size=len(augmented),
        batch_size=training["batch_size_per_gpu"],
        accumulation=accumulation,
        max_epochs=training["max_epochs"],
    )
    warmup = training["warmup_optimizer_steps"]
    scheduler = torch.optim.lr_scheduler.LambdaLR(
        optimizer,
        lambda step: (step + 1) / warmup if step < warmup else 0.5 * (
            1 + math.cos(math.pi * (step - warmup) / max(1, total_steps - warmup))
        ),
    )
    scaler = torch.amp.GradScaler("cuda", enabled=runtime["mixed_precision"])
    start_epoch, best_metric, stale_epochs = 0, float("-inf"), 0
    optimizer_attempts = optimizer_updates = skipped_optimizer_updates = 0
    if resume:
        checkpoint = _load_checkpoint(resume, torch)
        if checkpoint["run_id"] != config["run_id"]:
            raise ValueError("resume checkpoint belongs to another run")
        _restore_rng_state(checkpoint.get("rng_state"), torch)
        model.load_state_dict(checkpoint["model"])
        optimizer.load_state_dict(checkpoint["optimizer"])
        scheduler.load_state_dict(checkpoint["scheduler"])
        scaler.load_state_dict(checkpoint["scaler"])
        start_epoch, resume_batch_index, resume_running = _resume_position(checkpoint)
        best_metric, stale_epochs = checkpoint["best_metric"], checkpoint["stale_epochs"]
        optimizer_attempts = checkpoint.get("optimizer_attempts", 0)
        optimizer_updates = checkpoint.get("optimizer_updates", 0)
        skipped_optimizer_updates = checkpoint.get("skipped_optimizer_updates", 0)
    else:
        resume_batch_index, resume_running = 0, 0.0
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    metrics_path = output / "metrics.jsonl"
    optimizer.zero_grad(set_to_none=True)
    diagnostic_batches_processed = 0
    for epoch in range(start_epoch, training["max_epochs"]):
        augmented.set_epoch(epoch)
        loader_seed, worker_count = _epoch_loader_runtime(
            seed=runtime["seed"], epoch=epoch,
            runtime_workers=data_loader_num_workers,
            diagnostic_mode=diagnostic_mode,
            diagnostic_num_workers=diagnostic_num_workers,
        )
        generator = torch.Generator().manual_seed(loader_seed)
        train_loader = DataLoader(
            augmented, batch_size=training["batch_size_per_gpu"], shuffle=True,
            collate_fn=collate_fn, generator=generator,
            **_loader_process_options(worker_count),
        )
        model.train()
        running = resume_running if epoch == start_epoch else 0.0
        heartbeat_started = time.monotonic()
        print(json.dumps({
            "event": "epoch_start", "epoch": epoch + 1,
            "batches_in_epoch": len(train_loader), "resume_batch_index": resume_batch_index,
            "num_workers": worker_count, **_memory_snapshot(torch, device),
        }, sort_keys=True), flush=True)
        for batch_index, (images, targets) in enumerate(train_loader):
            if epoch == start_epoch and batch_index < resume_batch_index:
                continue
            metadata = [target.pop("_diagnostic", {}) for target in targets]
            if diagnostic_mode:
                torch.cuda.reset_peak_memory_stats(device)
                _emit_diagnostic(
                    "batch_received", torch=torch, device=device,
                    batch=batch_index + 1, metadata=metadata,
                )
            images = [image.to(device) for image in images]
            targets = [{key: value.to(device) for key, value in target.items()} for target in targets]
            if diagnostic_mode:
                _emit_diagnostic(
                    "before_forward", torch=torch, device=device,
                    batch=batch_index + 1, metadata=metadata,
                )
            with torch.amp.autocast("cuda", enabled=runtime["mixed_precision"]):
                losses = model(images, targets)
                loss = sum(losses.values()) / accumulation
            if diagnostic_mode:
                _emit_diagnostic(
                    "after_forward", torch=torch, device=device,
                    batch=batch_index + 1, metadata=metadata,
                    losses={key: float(value.detach().item()) for key, value in losses.items()},
                )
            if not torch.isfinite(loss):
                raise RuntimeError("non-finite training loss")
            if diagnostic_mode:
                _emit_diagnostic(
                    "before_backward", torch=torch, device=device,
                    batch=batch_index + 1, metadata=metadata,
                )
            scaler.scale(loss).backward()
            if diagnostic_mode:
                _emit_diagnostic(
                    "after_backward", torch=torch, device=device,
                    batch=batch_index + 1, metadata=metadata,
                )
            batch_loss = _unscaled_loss_value(loss, accumulation)
            running += batch_loss
            if (batch_index + 1) % accumulation == 0 or batch_index + 1 == len(train_loader):
                scaler.unscale_(optimizer)
                torch.nn.utils.clip_grad_norm_(model.parameters(), training["gradient_clip_norm"])
                if diagnostic_mode:
                    _emit_diagnostic(
                        "before_optimizer_attempt", torch=torch, device=device,
                        batch=batch_index + 1, metadata=metadata,
                    )
                step = _step_optimizer_with_amp(
                    scaler=scaler, optimizer=optimizer, scheduler=scheduler,
                )
                optimizer_attempts += 1
                if step["optimizer_step_performed"]:
                    optimizer_updates += 1
                else:
                    skipped_optimizer_updates += 1
                optimizer.zero_grad(set_to_none=True)
                if diagnostic_mode:
                    _emit_diagnostic(
                        "after_optimizer_attempt", torch=torch, device=device,
                        batch=batch_index + 1, metadata=metadata, **step,
                        optimizer_attempts=optimizer_attempts,
                        optimizer_updates=optimizer_updates,
                        skipped_optimizer_updates=skipped_optimizer_updates,
                    )
                final_batch = batch_index + 1 == len(train_loader)
                if _should_log_progress(
                    optimizer_attempts=optimizer_attempts,
                    skipped=not step["optimizer_step_performed"],
                    final_batch=final_batch,
                ):
                    print(json.dumps({
                        "event": "optimizer_progress",
                        "epoch": epoch + 1,
                        "batch": batch_index + 1,
                        "batches_in_epoch": len(train_loader),
                        "optimizer_attempts": optimizer_attempts,
                        "optimizer_updates": optimizer_updates,
                        "skipped_optimizer_updates": skipped_optimizer_updates,
                        "loss": batch_loss,
                        "learning_rate": optimizer.param_groups[0]["lr"],
                        **step,
                    }, sort_keys=True), flush=True)
                if (
                    step["optimizer_step_performed"] and
                    _should_checkpoint_in_epoch(
                        optimizer_updates=optimizer_updates,
                        interval=checkpoint_every_optimizer_updates,
                    )
                ):
                    checkpoint_path = output / "checkpoint-progress.pt"
                    checkpoint_started = time.monotonic()
                    print(json.dumps({
                        "event": "checkpoint_start", "epoch": epoch + 1,
                        "batch": batch_index + 1, "optimizer_updates": optimizer_updates,
                        "path": str(checkpoint_path),
                    }, sort_keys=True), flush=True)
                    _save_checkpoint(
                        checkpoint_path, model=model, optimizer=optimizer,
                        scheduler=scheduler, scaler=scaler, epoch=epoch,
                        best_metric=best_metric, stale_epochs=stale_epochs,
                        optimizer_attempts=optimizer_attempts, optimizer_updates=optimizer_updates,
                        skipped_optimizer_updates=skipped_optimizer_updates, config=config,
                        epoch_complete=False, next_batch_index=batch_index + 1,
                        epoch_running_loss=running,
                    )
                    print(json.dumps({
                        "event": "checkpoint_complete", "epoch": epoch + 1,
                        "batch": batch_index + 1, "optimizer_updates": optimizer_updates,
                        "path": str(checkpoint_path),
                        "duration_seconds": round(time.monotonic() - checkpoint_started, 3),
                    }, sort_keys=True), flush=True)
            final_batch = batch_index + 1 == len(train_loader)
            if _should_emit_heartbeat(
                completed_batches=batch_index + 1,
                interval=heartbeat_every_batches,
                final_batch=final_batch,
            ):
                print(json.dumps({
                    "event": "training_heartbeat", "epoch": epoch + 1,
                    "batch": batch_index + 1, "batches_in_epoch": len(train_loader),
                    "optimizer_attempts": optimizer_attempts,
                    "optimizer_updates": optimizer_updates,
                    "skipped_optimizer_updates": skipped_optimizer_updates,
                    "last_batch_loss": batch_loss,
                    "elapsed_since_epoch_start_seconds": round(time.monotonic() - heartbeat_started, 3),
                    **_memory_snapshot(torch, device),
                }, sort_keys=True), flush=True)
            if diagnostic_mode:
                diagnostic_batches_processed += 1
                if diagnostic_batches_processed >= diagnostic_max_batches:
                    _emit_diagnostic(
                        "diagnostic_complete", torch=torch, device=device,
                        batch=batch_index + 1, metadata=metadata,
                        diagnostic_batches_processed=diagnostic_batches_processed,
                        optimizer_attempts=optimizer_attempts,
                        optimizer_updates=optimizer_updates,
                        skipped_optimizer_updates=skipped_optimizer_updates,
                    )
                    return {
                        "status": "DIAGNOSTIC_COMPLETE",
                        "batches": diagnostic_batches_processed,
                        "optimizer_attempts": optimizer_attempts,
                        "optimizer_updates": optimizer_updates,
                        "skipped_optimizer_updates": skipped_optimizer_updates,
                    }
        validation = _evaluate(
            model, val_loader, device, config["evaluation"]["score_threshold"],
            heartbeat_every_batches=heartbeat_every_batches,
        )
        selection = float(validation["map"])
        record = {"epoch": epoch + 1, "train_loss": running / len(train_loader), **validation}
        with metrics_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
        improved = selection >= best_metric + config["evaluation"]["early_stopping"]["minimum_improvement"]
        best_metric, stale_epochs = (selection, 0) if improved else (best_metric, stale_epochs + 1)
        latest = output / "checkpoint-latest.pt"
        _save_checkpoint(latest, model=model, optimizer=optimizer, scheduler=scheduler, scaler=scaler,
                         epoch=epoch, best_metric=best_metric, stale_epochs=stale_epochs,
                         optimizer_attempts=optimizer_attempts, optimizer_updates=optimizer_updates,
                         skipped_optimizer_updates=skipped_optimizer_updates, config=config,
                         epoch_complete=True)
        if improved:
            _save_checkpoint(output / "checkpoint-best.pt", model=model, optimizer=optimizer,
                             scheduler=scheduler, scaler=scaler, epoch=epoch, best_metric=best_metric,
                             stale_epochs=stale_epochs, optimizer_attempts=optimizer_attempts,
                             optimizer_updates=optimizer_updates,
                             skipped_optimizer_updates=skipped_optimizer_updates, config=config,
                             epoch_complete=True)
        stopping = config["evaluation"]["early_stopping"]
        if epoch + 1 >= stopping["minimum_epochs"] and stale_epochs >= stopping["patience_epochs"]:
            break


def main(argv=None):
    args = parse_args(argv)
    validation = validate_package(args.config, args.adapter_root, args.initialization)
    print(json.dumps(validation, indent=2, sort_keys=True))
    if args.validate_only:
        return 0
    if not args.authorize_training:
        raise SystemExit("training is locked; pass --authorize-training only after explicit approval")
    train(
        args.config, args.adapter_root, args.initialization, args.output, args.resume,
        diagnostic_max_batches=args.diagnostic_max_batches,
        diagnostic_num_workers=args.diagnostic_num_workers,
        data_loader_num_workers=args.num_workers,
        heartbeat_every_batches=args.heartbeat_every_batches,
        checkpoint_every_optimizer_updates=args.checkpoint_every_optimizer_updates,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
