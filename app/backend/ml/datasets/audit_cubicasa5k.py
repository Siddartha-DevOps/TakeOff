"""Read-only structural and integrity audit for an extracted CubiCasa5K tree.

The command never converts, moves, or edits source files. It records exact
split membership, SVG taxonomies, PNG/SVG integrity, missing floor-image pairs,
empty files, and byte-identical duplicates in a compact JSON report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, UnidentifiedImageError


FLOOR_IMAGE = re.compile(r"^F(?P<floor>\d+)_(?P<kind>original|scaled)\.png$", re.IGNORECASE)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inspect_png(path: Path) -> dict:
    result = {"path": path.as_posix(), "size": path.stat().st_size, "sha256": "", "width": 0, "height": 0,
              "error": None}
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            result["width"], result["height"] = image.size
        result["sha256"] = _sha256(path)
    except (OSError, UnidentifiedImageError) as exc:
        result["error"] = str(exc)
    return result


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _inspect_svg(path: Path) -> dict:
    result = {
        "path": path.as_posix(), "size": path.stat().st_size, "sha256": "", "error": None,
        "groups": Counter(), "spaces": Counter(), "walls": Counter(), "doors": Counter(),
        "windows": Counter(), "fixed_furniture": Counter(), "polygons": 0,
    }
    try:
        result["sha256"] = _sha256(path)
        root = ET.parse(path).getroot()
        for element in root.iter():
            if _local(element.tag) == "polygon":
                result["polygons"] += 1
            if _local(element.tag) != "g":
                continue
            classes = (element.get("class") or "").split()
            if not classes:
                continue
            result["groups"][classes[0]] += 1
            detail = " ".join(classes[1:]) or "<unspecified>"
            if classes[0] == "Space":
                result["spaces"][classes[1] if len(classes) > 1 else "<unspecified>"] += 1
            elif classes[0] == "Wall":
                result["walls"][detail] += 1
            elif classes[0] == "Door":
                result["doors"][detail] += 1
            elif classes[0] == "Window":
                result["windows"][detail] += 1
            elif classes[0] == "FixedFurniture":
                result["fixed_furniture"][detail] += 1
    except (OSError, ET.ParseError) as exc:
        result["error"] = str(exc)
    return result


def _read_split(path: Path) -> list[str]:
    return [line.strip().replace("\\", "/").strip("/") for line in path.read_text(encoding="utf-8-sig").splitlines()
            if line.strip()]


def _counter_dict(counter: Counter) -> dict[str, int]:
    return dict(sorted(counter.items(), key=lambda item: (-item[1], item[0])))


def audit_cubicasa(root: str | Path, *, archive_path: str | Path | None = None,
                    archive_sha256: str | None = None, workers: int = 8) -> dict:
    root = Path(root).resolve()
    plans = sorted(path.parent for path in root.rglob("model.svg"))
    plan_ids = {path.relative_to(root).as_posix() for path in plans}
    pngs = sorted(root.rglob("*.png"))
    svgs = sorted(root.rglob("*.svg"))
    all_files = sorted(path for path in root.rglob("*") if path.is_file())
    empty_files = [path.relative_to(root).as_posix() for path in all_files if path.stat().st_size == 0]

    split_members: dict[str, list[str]] = {}
    split_duplicates: dict[str, list[str]] = {}
    for split in ("train", "val", "test"):
        entries = _read_split(root / f"{split}.txt")
        split_members[split] = entries
        counts = Counter(entries)
        split_duplicates[split] = sorted(key for key, value in counts.items() if value > 1)
    split_sets = {key: set(value) for key, value in split_members.items()}
    split_overlaps = {
        "train_val": sorted(split_sets["train"] & split_sets["val"]),
        "train_test": sorted(split_sets["train"] & split_sets["test"]),
        "val_test": sorted(split_sets["val"] & split_sets["test"]),
    }
    split_union = set().union(*split_sets.values())

    pages_by_plan: dict[str, dict[str, set[str]]] = {}
    missing_pairs: list[dict] = []
    page_counts_by_split = Counter()
    category_counts = Counter()
    for plan in plans:
        plan_id = plan.relative_to(root).as_posix()
        category_counts[plan.relative_to(root).parts[0]] += 1
        floors = {"original": set(), "scaled": set()}
        for image in plan.glob("*.png"):
            match = FLOOR_IMAGE.match(image.name)
            if match:
                floors[match.group("kind").lower()].add(match.group("floor"))
        pages_by_plan[plan_id] = floors
        missing_original = sorted(floors["scaled"] - floors["original"])
        missing_scaled = sorted(floors["original"] - floors["scaled"])
        if missing_original or missing_scaled:
            missing_pairs.append({"plan": plan_id, "missing_original": missing_original, "missing_scaled": missing_scaled})
        for split, members in split_sets.items():
            if plan_id in members:
                page_counts_by_split[split] += len(floors["original"])

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        png_results = list(pool.map(_inspect_png, pngs))
        svg_results = list(pool.map(_inspect_svg, svgs))

    png_hashes: dict[str, list[str]] = defaultdict(list)
    for result in png_results:
        if result["sha256"]:
            png_hashes[result["sha256"]].append(Path(result["path"]).relative_to(root).as_posix())
    svg_hashes: dict[str, list[str]] = defaultdict(list)
    for result in svg_results:
        if result["sha256"]:
            svg_hashes[result["sha256"]].append(Path(result["path"]).relative_to(root).as_posix())

    aggregate = {name: Counter() for name in ("groups", "spaces", "walls", "doors", "windows", "fixed_furniture")}
    polygon_count = 0
    for result in svg_results:
        polygon_count += result["polygons"]
        for name in aggregate:
            aggregate[name].update(result[name])

    archive = Path(archive_path).resolve() if archive_path else None
    return {
        "schema_version": 1,
        "dataset": "CubiCasa5K",
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "archive_path": str(archive) if archive else None,
            "archive_bytes": archive.stat().st_size if archive and archive.is_file() else None,
            "archive_sha256": archive_sha256,
            "raw_root": str(root),
            "license_files_in_archive": [],
        },
        "counts": {
            "plans_with_model_svg": len(plans),
            "floor_pages_original": sum(len(value["original"]) for value in pages_by_plan.values()),
            "floor_pages_scaled": sum(len(value["scaled"]) for value in pages_by_plan.values()),
            "png_files": len(pngs),
            "svg_files": len(svgs),
            "text_files": len(list(root.glob("*.txt"))),
            "all_files": len(all_files),
            "svg_polygons": polygon_count,
        },
        "structure": {
            "plan_categories": _counter_dict(category_counts),
            "image_extensions": {".png": len(pngs)},
            "annotation_extensions": {".svg": len(svgs)},
        },
        "splits": {
            "plan_counts": {name: len(values) for name, values in split_members.items()},
            "original_page_counts": dict(page_counts_by_split),
            "duplicate_entries": split_duplicates,
            "overlaps": split_overlaps,
            "entries_missing_plan": {name: sorted(set(values) - plan_ids) for name, values in split_members.items()},
            "unassigned_plans": sorted(plan_ids - split_union),
        },
        "taxonomy": {name: _counter_dict(counter) for name, counter in aggregate.items()},
        "integrity": {
            "empty_files": empty_files,
            "png_errors": [{"path": Path(item["path"]).relative_to(root).as_posix(), "error": item["error"]}
                           for item in png_results if item["error"]],
            "svg_errors": [{"path": Path(item["path"]).relative_to(root).as_posix(), "error": item["error"]}
                           for item in svg_results if item["error"]],
            "missing_original_scaled_pairs": missing_pairs,
            "duplicate_png_groups": [paths for paths in png_hashes.values() if len(paths) > 1],
            "duplicate_svg_groups": [paths for paths in svg_hashes.values() if len(paths) > 1],
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--archive-sha256")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args(argv)
    report = audit_cubicasa(args.root, archive_path=args.archive, archive_sha256=args.archive_sha256,
                            workers=args.workers)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"counts": report["counts"], "splits": report["splits"],
                      "integrity_summary": {key: len(value) for key, value in report["integrity"].items()}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
