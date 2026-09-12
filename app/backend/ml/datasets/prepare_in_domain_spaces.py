"""Create a deterministic project-level split for approved in-domain sheets.

This command never downloads data and never invents samples.  It assigns the
source-manifest records as whole projects, writes a reviewable split manifest,
and can optionally materialize the approved YOLO files for training later.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections import defaultdict
from pathlib import Path


SPLITS = ("train", "val", "test", "golden")


def _stable_key(seed: str, project_id: str) -> str:
    return hashlib.sha256(f"{seed}:{project_id}".encode()).hexdigest()


def assign_project_splits(samples: list[dict], config: dict) -> dict:
    """Assign complete projects while preserving explicit reviewed splits."""
    by_project: dict[str, list[dict]] = defaultdict(list)
    for sample in samples:
        if sample.get("intake_eligibility", {}).get("status") != "eligible":
            raise ValueError(
                f"sample {sample.get('sample_id', '<unknown>')} is not intake-eligible"
            )
        project_id = str(sample.get("project_id", "")).strip()
        if not project_id:
            raise ValueError(f"sample {sample.get('sample_id', '<unknown>')} has no project_id")
        by_project[project_id].append(dict(sample))

    assignments: dict[str, str] = {}
    for project_id, project_samples in by_project.items():
        explicit = {item.get("split") for item in project_samples if item.get("split") is not None}
        if len(explicit) > 1:
            raise ValueError(f"project {project_id} is assigned to multiple splits: {sorted(explicit)}")
        if explicit:
            split = explicit.pop()
            if split not in SPLITS:
                raise ValueError(f"project {project_id} has invalid split {split!r}")
            assignments[project_id] = split

    counts = {split: 0 for split in SPLITS}
    for project_id, split in assignments.items():
        counts[split] += len(by_project[project_id])

    seed = str(config["split_seed"])
    unassigned = sorted(
        (project_id for project_id in by_project if project_id not in assignments),
        key=lambda project_id: _stable_key(seed, project_id),
    )

    # Golden membership is never inferred from ordinary samples.  Every page in
    # a candidate project needs explicit approval and untouched status.
    golden_candidates = [
        project_id for project_id in unassigned
        if all(item.get("golden_approved") is True and item.get("untouched") is True
               for item in by_project[project_id])
    ]
    for project_id in golden_candidates:
        if counts["golden"] >= int(config["target_counts"]["golden"]):
            break
        assignments[project_id] = "golden"
        counts["golden"] += len(by_project[project_id])

    for project_id in unassigned:
        if project_id in assignments:
            continue
        split = max(
            ("train", "val", "test"),
            key=lambda name: int(config["target_counts"][name]) - counts[name],
        )
        assignments[project_id] = split
        counts[split] += len(by_project[project_id])

    assigned_samples: list[dict] = []
    projects = {split: [] for split in SPLITS}
    for project_id in sorted(by_project):
        split = assignments[project_id]
        projects[split].append(project_id)
        for item in sorted(by_project[project_id], key=lambda value: value["sample_id"]):
            item["split"] = split
            assigned_samples.append(item)

    return {
        "schema_version": 1,
        "dataset_name": config["dataset_name"],
        "status": "PREPARED_NOT_VALIDATED" if assigned_samples else "NOT_READY",
        "split_policy": "project_level_no_page_or_revision_leakage",
        "target_counts": config["target_counts"],
        "actual_counts": counts,
        "projects": projects,
        "samples": assigned_samples,
    }


def materialize_yolo(split_manifest: dict, source_root: Path, output_root: Path, classes: list[str]) -> None:
    """Copy manifest-approved sources into the canonical four-split layout."""
    if output_root.exists() and any(output_root.iterdir()):
        raise ValueError(f"refusing to overwrite non-empty output directory: {output_root}")
    groups: dict[str, str] = {}
    for sample in split_manifest["samples"]:
        split = sample["split"]
        image_source = (source_root / sample["image_path"]).resolve()
        label_source = (source_root / sample["label_path"]).resolve()
        if source_root.resolve() not in image_source.parents or source_root.resolve() not in label_source.parents:
            raise ValueError(f"sample {sample['sample_id']} escapes source root")
        if not image_source.is_file() or not label_source.is_file():
            raise FileNotFoundError(f"sample {sample['sample_id']} source image/label is missing")
        image_name = f"{sample['sample_id']}{image_source.suffix.lower()}"
        image_target = output_root / "images" / split / image_name
        label_target = output_root / "labels" / split / f"{sample['sample_id']}.txt"
        image_target.parent.mkdir(parents=True, exist_ok=True)
        label_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(image_source, image_target)
        shutil.copy2(label_source, label_target)
        groups[f"images/{split}/{image_name}"] = sample["project_id"]

    names = ", ".join(classes)
    (output_root / "data.yaml").write_text(
        f"path: {output_root.resolve()}\n"
        "train: images/train\nval: images/val\ntest: images/test\n"
        f"nc: {len(classes)}\nnames: [{names}]\n",
        encoding="utf-8",
    )
    (output_root / "groups.json").write_text(
        json.dumps({"groups": groups}, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output_root / "split_manifest.json").write_text(
        json.dumps(split_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--out-manifest", required=True, type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--materialize", type=Path)
    args = parser.parse_args(argv)

    source = json.loads(args.manifest.read_text(encoding="utf-8"))
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if source.get("classes") != config.get("classes"):
        raise ValueError("source manifest class taxonomy does not match configuration")
    result = assign_project_splits(source.get("samples", []), config)
    args.out_manifest.parent.mkdir(parents=True, exist_ok=True)
    args.out_manifest.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.materialize:
        if not args.source_root:
            raise ValueError("--source-root is required with --materialize")
        materialize_yolo(result, args.source_root, args.materialize, config["classes"])
    print(json.dumps({"status": result["status"], "actual_counts": result["actual_counts"]}, indent=2))
    return 0 if result["samples"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
