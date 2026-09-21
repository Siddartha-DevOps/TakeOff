"""Build and run the bounded Kaggle GPU preflight for the frozen room adapter."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
from pathlib import Path
from typing import Any

from ml.datasets.adapt_swiss_rooms_maskrcnn_poc import decode_uncompressed_rle
from ml.training.maskrcnn_rooms import CocoRLEMaskDataset, build_maskrcnn, collate_fn


PREFLIGHT_VERSION = "swiss-rooms-maskrcnn-kaggle-preflight-v2"
FULL_MANIFEST_SHA256 = "61966eb947ba0ffc2dbc094c33142246b2be3a9cdba085c9f0cb36e93279ce29"
EXPECTED_PYTHON_VERSION = (3, 12)
EXPECTED_TORCH_VERSION = "2.5.1"
EXPECTED_TORCHVISION_VERSION = "0.20.1"
MINIMUM_VRAM_BYTES = 14 * 1024**3
EXPECTED_FLOOR_COUNT = 13902


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def require_python_version(version: tuple[int, int] | None = None) -> None:
    """Reject runtimes other than the pinned Kaggle Python minor version."""
    current = version or sys.version_info[:2]
    if tuple(current) != EXPECTED_PYTHON_VERSION:
        required = ".".join(map(str, EXPECTED_PYTHON_VERSION))
        found = ".".join(map(str, current))
        raise RuntimeError(f"Python {required} required, found {found}")


def _write_or_verify(path: Path, payload: bytes) -> None:
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError(f"existing preflight output differs: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def _copy_or_verify(source: Path, destination: Path, expected_sha256: str) -> None:
    if _sha256(source) != expected_sha256:
        raise ValueError(f"source checksum mismatch: {source}")
    if destination.exists():
        if _sha256(destination) != expected_sha256:
            raise ValueError(f"existing preflight copy differs: {destination}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    if _sha256(destination) != expected_sha256:
        raise ValueError(f"copied preflight file checksum mismatch: {destination}")


def select_preflight_floors(full_manifest: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Select stable real samples: train+holes, validation, and train negative."""
    floors = sorted(full_manifest["floors"], key=lambda row: row["floor_key"])
    predicates = (
        ("train_hole", lambda row: row["split"] == "train" and row["hole_instance_count"] > 0),
        ("validation_positive", lambda row: row["split"] == "val" and row["converted_instance_count"] > 0),
        ("intentional_negative", lambda row: row["split"] == "train" and row["converted_instance_count"] == 0),
    )
    selected: list[tuple[str, dict[str, Any]]] = []
    for role, predicate in predicates:
        try:
            selected.append((role, next(row for row in floors if predicate(row))))
        except StopIteration as exc:
            raise ValueError(f"frozen adapter has no sample for required role {role}") from exc
    if len({row["floor_key"] for _, row in selected}) != len(selected):
        raise ValueError("preflight sample roles selected the same floor")
    return selected


def build_kaggle_bundle(source_manifest: str | Path, output_dir: str | Path) -> dict[str, Any]:
    """Create a small portable bundle without modifying the frozen adapter."""
    source_manifest = Path(source_manifest)
    output_dir = Path(output_dir)
    if _sha256(source_manifest) != FULL_MANIFEST_SHA256:
        raise ValueError("frozen full-adapter manifest checksum mismatch")
    full_manifest = json.loads(source_manifest.read_text(encoding="utf-8"))
    if full_manifest["summary"]["floor_count"] != EXPECTED_FLOOR_COUNT:
        raise ValueError("unexpected frozen floor count")
    if full_manifest["summary"]["rejected_instance_count"] != 0:
        raise ValueError("frozen adapter contains rejected instances")

    frozen_copy = output_dir / "frozen-full-adapter-manifest.json"
    _copy_or_verify(source_manifest, frozen_copy, FULL_MANIFEST_SHA256)
    portable_floors: list[dict[str, Any]] = []
    samples: list[dict[str, Any]] = []
    for role, floor in select_preflight_floors(full_manifest):
        source_annotation = Path(floor["annotation_path"])
        source_image = Path(floor["image_path"])
        stem = source_annotation.stem
        image_relative = Path("samples") / "images" / floor["split"] / f"{stem}.png"
        annotation_relative = Path("samples") / "annotations" / floor["split"] / f"{stem}.json"
        _copy_or_verify(source_image, output_dir / image_relative, floor["image_sha256"])

        source_shard_bytes = source_annotation.read_bytes()
        if hashlib.sha256(source_shard_bytes).hexdigest() != floor["annotation_sha256"]:
            raise ValueError(f"source annotation checksum mismatch: {source_annotation}")
        portable_shard = json.loads(source_shard_bytes)
        portable_shard["image"]["file_name"] = image_relative.as_posix()
        portable_shard_bytes = _canonical_json(portable_shard)
        _write_or_verify(output_dir / annotation_relative, portable_shard_bytes)
        portable_annotation_sha = hashlib.sha256(portable_shard_bytes).hexdigest()

        portable_floor = dict(floor)
        portable_floor["annotation_path"] = annotation_relative.as_posix()
        portable_floor["annotation_sha256"] = portable_annotation_sha
        portable_floor["image_path"] = image_relative.as_posix()
        portable_floors.append(portable_floor)
        samples.append({
            "role": role,
            "floor_key": floor["floor_key"],
            "split": floor["split"],
            "source_annotation_sha256": floor["annotation_sha256"],
            "source_image_sha256": floor["image_sha256"],
            "portable_annotation_sha256": portable_annotation_sha,
            "annotation_path": annotation_relative.as_posix(),
            "image_path": image_relative.as_posix(),
            "authoritative_instance_count": floor["authoritative_instance_count"],
            "hole_instance_count": floor["hole_instance_count"],
        })

    adapter_manifest = {
        "schema_version": 1,
        "adapter_version": PREFLIGHT_VERSION,
        "architecture_target": "torchvision-maskrcnn-resnet50-fpn-v2",
        "source_training_manifest_sha256": full_manifest["source_training_manifest_sha256"],
        "taxonomy": full_manifest["taxonomy"],
        "floors": portable_floors,
    }
    adapter_path = output_dir / "preflight-adapter-manifest.json"
    _write_or_verify(adapter_path, _canonical_json(adapter_manifest))
    bundle_manifest = {
        "preflight_version": PREFLIGHT_VERSION,
        "frozen_full_adapter_manifest_sha256": FULL_MANIFEST_SHA256,
        "portable_adapter_manifest": adapter_path.name,
        "portable_adapter_manifest_sha256": _sha256(adapter_path),
        "samples": samples,
    }
    bundle_path = output_dir / "preflight-bundle-manifest.json"
    _write_or_verify(bundle_path, _canonical_json(bundle_manifest))
    _write_or_verify(bundle_path.with_suffix(".json.sha256"), (_sha256(bundle_path) + "\n").encode("ascii"))
    return {"bundle_manifest": str(bundle_path), "bundle_sha256": _sha256(bundle_path), "samples": samples}


def validate_inference_output(output: dict[str, Any], taxonomy: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate torchvision output and map its first result to TakeOff fields."""
    required = {"boxes", "labels", "scores", "masks"}
    if not required.issubset(output):
        raise ValueError(f"Mask R-CNN output missing keys: {sorted(required - set(output))}")
    lengths = {key: len(output[key]) for key in required}
    if len(set(lengths.values())) != 1:
        raise ValueError(f"Mask R-CNN output lengths differ: {lengths}")
    names = {int(row["id"]): row["name"] for row in taxonomy}
    if not lengths["labels"]:
        return {"compatible": True, "prediction_count": 0, "mapped_example": None}
    label_id = int(output["labels"][0].detach().cpu().item())
    score = float(output["scores"][0].detach().cpu().item())
    bbox = output["boxes"][0].detach().cpu().tolist()
    mask = output["masks"][0, 0].detach().cpu()
    if label_id not in names or not math.isfinite(score) or len(bbox) != 4 or mask.ndim != 2:
        raise ValueError("Mask R-CNN output cannot be mapped to the TakeOff label/score/bbox/mask contract")
    return {
        "compatible": True,
        "prediction_count": lengths["labels"],
        "mapped_example": {"label": names[label_id], "score": score, "bbox": bbox, "mask_shape": list(mask.shape)},
    }


def validate_gpu_preflight_report(report: dict[str, Any]) -> None:
    """Validate the persisted evidence emitted by the bounded Kaggle preflight."""
    if report.get("preflight_version") != PREFLIGHT_VERSION:
        raise ValueError("unexpected GPU preflight version")
    if report.get("torch", "").split("+")[0] != EXPECTED_TORCH_VERSION:
        raise ValueError("unexpected torch version in GPU preflight report")
    if report.get("torchvision", "").split("+")[0] != EXPECTED_TORCHVISION_VERSION:
        raise ValueError("unexpected torchvision version in GPU preflight report")
    if report.get("cuda") != "12.1" or not report.get("gpu"):
        raise ValueError("unexpected CUDA/GPU runtime in GPU preflight report")
    if not math.isfinite(float(report.get("vram_gib", 0))) or float(report["vram_gib"]) < 14:
        raise ValueError("GPU preflight report does not prove the minimum VRAM")
    if report.get("dataset_samples") != 3 or int(report.get("hole_instances_checked", 0)) < 1:
        raise ValueError("GPU preflight dataset evidence is incomplete")
    if report.get("intentional_negative_verified") is not True:
        raise ValueError("intentional negative was not verified")
    required_losses = {
        "loss_box_reg", "loss_classifier", "loss_mask", "loss_objectness", "loss_rpn_box_reg",
    }
    losses = report.get("losses")
    if not isinstance(losses, dict) or set(losses) != required_losses:
        raise ValueError("GPU preflight loss set is incomplete")
    loss_values = [float(value) for value in losses.values()]
    total_loss = float(report.get("total_loss", float("nan")))
    if not all(math.isfinite(value) and value >= 0 for value in loss_values) \
            or not math.isfinite(total_loss) or not math.isclose(sum(loss_values), total_loss, rel_tol=1e-6):
        raise ValueError("GPU preflight losses are non-finite or inconsistent")
    if report.get("backward") is not True or report.get("optimizer_step") is not True:
        raise ValueError("GPU preflight backward/optimizer step did not complete")
    allocated = float(report.get("peak_allocated_gib", float("nan")))
    reserved = float(report.get("peak_reserved_gib", float("nan")))
    vram = float(report["vram_gib"])
    if not all(math.isfinite(value) for value in (allocated, reserved)) \
            or allocated <= 0 or reserved < allocated or reserved >= vram:
        raise ValueError("GPU memory evidence is invalid or exceeds available VRAM")
    contract = report.get("inference_contract")
    if not isinstance(contract, dict) or contract.get("compatible") is not True:
        raise ValueError("TakeOff inference output contract is not compatible")
    prediction_count = int(contract.get("prediction_count", -1))
    example = contract.get("mapped_example")
    if prediction_count < 0 or (prediction_count > 0 and not isinstance(example, dict)):
        raise ValueError("GPU inference evidence is incomplete")
    if example is not None:
        bbox = example.get("bbox")
        mask_shape = example.get("mask_shape")
        score = float(example.get("score", float("nan")))
        if not isinstance(example.get("label"), str) or len(bbox or []) != 4 \
                or not all(math.isfinite(float(value)) for value in bbox) \
                or len(mask_shape or []) != 2 or not all(int(value) > 0 for value in mask_shape) \
                or not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError("mapped inference example is invalid")
    if report.get("training_started") is not False:
        raise ValueError("GPU preflight report indicates a training run")


def run_gpu_preflight(bundle_dir: str | Path) -> dict[str, Any]:
    """Run exactly one CUDA train step and one inference pass; never a training loop."""
    import torch
    import torchvision
    from torch.utils.data import DataLoader

    bundle_dir = Path(bundle_dir)
    require_python_version()
    if torch.__version__.split("+")[0] != EXPECTED_TORCH_VERSION:
        raise RuntimeError(f"torch {EXPECTED_TORCH_VERSION} required, found {torch.__version__}")
    if torchvision.__version__.split("+")[0] != EXPECTED_TORCHVISION_VERSION:
        raise RuntimeError(f"torchvision {EXPECTED_TORCHVISION_VERSION} required, found {torchvision.__version__}")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU is required")
    device = torch.device("cuda:0")
    properties = torch.cuda.get_device_properties(device)
    if properties.total_memory < MINIMUM_VRAM_BYTES:
        raise RuntimeError(f"at least 14 GiB usable VRAM required, found {properties.total_memory / 1024**3:.2f} GiB")

    frozen_manifest = bundle_dir / "frozen-full-adapter-manifest.json"
    if _sha256(frozen_manifest) != FULL_MANIFEST_SHA256:
        raise ValueError("uploaded frozen manifest checksum mismatch")
    bundle = json.loads((bundle_dir / "preflight-bundle-manifest.json").read_text(encoding="utf-8"))
    adapter_path = bundle_dir / bundle["portable_adapter_manifest"]
    if _sha256(adapter_path) != bundle["portable_adapter_manifest_sha256"]:
        raise ValueError("portable adapter manifest checksum mismatch")
    dataset = CocoRLEMaskDataset(adapter_path, bundle_dir / "samples" / "images")
    loader = DataLoader(dataset, batch_size=1, shuffle=False, num_workers=0, collate_fn=collate_fn)
    loaded = list(loader)
    if len(loaded) != 3:
        raise ValueError("expected exactly three deterministic preflight samples")

    role_to_index = {sample["role"]: index for index, sample in enumerate(bundle["samples"])}
    hole_index = role_to_index["train_hole"]
    negative_index = role_to_index["intentional_negative"]
    if loaded[negative_index][1][0]["masks"].shape[0] != 0:
        raise ValueError("intentional negative sample contains instances")
    hole_shard_path = Path(dataset.images[hole_index]["annotation_path"])
    if not hole_shard_path.is_absolute():
        hole_shard_path = adapter_path.parent / hole_shard_path
    hole_floor = json.loads(hole_shard_path.read_text(encoding="utf-8"))
    hole_annotations = [row for row in hole_floor["annotations"] if row["interior_ring_count"] > 0]
    if not hole_annotations:
        raise ValueError("hole-containing sample lost its hole instances")
    for annotation in hole_annotations:
        if int(decode_uncompressed_rle(annotation["segmentation"]).sum()) != int(annotation["area"]):
            raise ValueError("hole-containing RLE failed area round-trip")

    model = build_maskrcnn(num_classes=15, pretrained=False)
    model.transform.min_size = (1024,)
    model.transform.max_size = 1600
    model.to(device)
    optimizer = torch.optim.SGD(model.parameters(), lr=1e-5, momentum=0.9)
    train_images, train_targets = loaded[hole_index]
    train_images = [image.to(device) for image in train_images]
    train_targets = [{key: value.to(device) for key, value in target.items()} for target in train_targets]
    torch.cuda.reset_peak_memory_stats(device)
    model.train()
    optimizer.zero_grad(set_to_none=True)
    losses = model(train_images, train_targets)
    if not losses or not all(torch.isfinite(value).all().item() for value in losses.values()):
        raise RuntimeError("Mask R-CNN produced missing or non-finite losses")
    total_loss = sum(losses.values())
    total_loss.backward()
    optimizer.step()
    torch.cuda.synchronize(device)
    peak_allocated = torch.cuda.max_memory_allocated(device)
    peak_reserved = torch.cuda.max_memory_reserved(device)

    validation_index = role_to_index["validation_positive"]
    validation_images, _ = loaded[validation_index]
    model.eval()
    with torch.no_grad():
        output = model([validation_images[0].to(device)])[0]
    contract = validate_inference_output(output, dataset.coco["taxonomy"])
    return {
        "preflight_version": PREFLIGHT_VERSION,
        "gpu": properties.name,
        "cuda": torch.version.cuda,
        "vram_gib": round(properties.total_memory / 1024**3, 2),
        "torch": torch.__version__,
        "torchvision": torchvision.__version__,
        "dataset_samples": len(dataset),
        "hole_instances_checked": len(hole_annotations),
        "intentional_negative_verified": True,
        "losses": {key: float(value.detach().cpu().item()) for key, value in losses.items()},
        "total_loss": float(total_loss.detach().cpu().item()),
        "backward": True,
        "optimizer_step": True,
        "peak_allocated_gib": round(peak_allocated / 1024**3, 3),
        "peak_reserved_gib": round(peak_reserved / 1024**3, 3),
        "inference_contract": contract,
        "training_started": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build-bundle")
    build.add_argument("--source-manifest", required=True)
    build.add_argument("--output", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--bundle", required=True)
    run.add_argument("--report", default="maskrcnn-gpu-preflight-report.json")
    args = parser.parse_args()
    if args.command == "build-bundle":
        result = build_kaggle_bundle(args.source_manifest, args.output)
    else:
        result = run_gpu_preflight(args.bundle)
        Path(args.report).write_bytes(_canonical_json(result))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
