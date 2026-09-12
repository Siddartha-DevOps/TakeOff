"""Official ResPlan geometry -> leakage-audited YOLO segmentation dataset.

ResPlan is vector-only, so this converter renders clean monochrome floor plans
as the model input and exports the room geometries as YOLO polygons.  It keeps
the authors' canonical train/val/test split, excludes their augmented samples,
and prevents low-resolution semantic-layout duplicates from crossing splits.

The official pickle is loaded through a restricted unpickler which permits only
the three reconstruction functions present in the pinned release.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import pickle
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path
from typing import Iterable

from .bootstrap_public import SPACE_CLASSES, class_id
from .versioning import DatasetVersion, snapshot_dataset, write_version


UPSTREAM_COMMIT = "e2b78fe069aee1ab1e1828a612743f308e3c32a7"
RAW_ROOT = f"https://raw.githubusercontent.com/m-agour/ResPlan/{UPSTREAM_COMMIT}"
RESPLAN_ARCHIVE_URL = f"{RAW_ROOT}/ResPlan.zip"
RESPLAN_SPLIT_URL = f"{RAW_ROOT}/split.json"
RESPLAN_LICENSE_URL = f"{RAW_ROOT}/LICENSE"
RESPLAN_ARCHIVE_SHA256 = "f718de8865e51bbe93b49b584798e3c536ed6b4b8a5d32f01b56812f389aeb46"
RESPLAN_SPLIT_SHA256 = "7761df4ad4c860d7e89d1ef9c7004737cd407615b66ed9cde676d7087108c9a7"
SOURCE_LICENSE = "CC BY 4.0"

_ALLOWED_PICKLE_GLOBALS = {
    ("shapely.io", "from_wkb"),
    ("numpy._core.multiarray", "scalar"),
    ("numpy", "dtype"),
}


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class RestrictedResPlanUnpickler(pickle.Unpickler):
    """Reject executable pickle globals outside the pinned ResPlan schema."""

    def find_class(self, module: str, name: str):
        if (module, name) not in _ALLOWED_PICKLE_GLOBALS:
            raise pickle.UnpicklingError(f"forbidden ResPlan pickle global: {module}.{name}")
        return super().find_class(module, name)


def load_resplan(path: str | Path) -> list[dict]:
    """Load a pinned ResPlan pickle using the restricted class allowlist."""
    with Path(path).open("rb") as handle:
        plans = RestrictedResPlanUnpickler(handle).load()
    if not isinstance(plans, list) or not all(isinstance(plan, dict) for plan in plans):
        raise ValueError("ResPlan.pkl must contain a list of plan dictionaries")
    return plans


def _download(url: str, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url) as response, destination.open("wb") as output:  # noqa: S310
        shutil.copyfileobj(response, output)
    return destination


def prepare_resplan_source(source_dir: str | Path, *, download: bool = True) -> dict[str, Path]:
    """Download, verify and safely extract the pinned official source files."""
    source = Path(source_dir)
    archive = source / "ResPlan.zip"
    split = source / "split.json"
    license_path = source / "LICENSE"
    if download:
        if not archive.is_file():
            _download(RESPLAN_ARCHIVE_URL, archive)
        if not split.is_file():
            _download(RESPLAN_SPLIT_URL, split)
        if not license_path.is_file():
            _download(RESPLAN_LICENSE_URL, license_path)
    missing = [str(path) for path in (archive, split, license_path) if not path.is_file()]
    if missing:
        raise FileNotFoundError("missing ResPlan source files: " + ", ".join(missing))
    checks = ((archive, RESPLAN_ARCHIVE_SHA256), (split, RESPLAN_SPLIT_SHA256))
    for path, expected in checks:
        actual = file_sha256(path)
        if actual != expected:
            raise ValueError(f"checksum mismatch for {path}: expected {expected}, found {actual}")

    pickle_path = source / "extracted" / "ResPlan.pkl"
    if not pickle_path.is_file():
        pickle_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as bundle, bundle.open("ResPlan.pkl") as src, pickle_path.open("wb") as dst:
            shutil.copyfileobj(src, dst)
    return {"pickle": pickle_path, "split": split, "license": license_path, "archive": archive}


def iter_polygons(geometry) -> Iterable:
    """Yield non-empty polygons from Polygon/MultiPolygon-like geometry."""
    if geometry is None or getattr(geometry, "is_empty", True):
        return
    if getattr(geometry, "geom_type", None) == "Polygon":
        yield geometry
    elif hasattr(geometry, "geoms"):
        for part in geometry.geoms:
            if getattr(part, "geom_type", None) == "Polygon" and not part.is_empty:
                yield part


def _plan_bounds(plan: dict) -> tuple[float, float, float, float]:
    # `inner` excludes exterior balconies in some records. Fit every supervised
    # room plus the visible structure so no ground-truth point leaves canvas.
    polygons = [
        poly
        for key in (*SPACE_CLASSES, "wall", "door", "window", "front_door")
        for poly in iter_polygons(plan.get(key))
    ]
    if not polygons:
        polygons = list(iter_polygons(plan.get("inner")))
    if not polygons:
        raise ValueError(f"plan {plan.get('id')} has no renderable geometry")
    return (
        min(poly.bounds[0] for poly in polygons), min(poly.bounds[1] for poly in polygons),
        max(poly.bounds[2] for poly in polygons), max(poly.bounds[3] for poly in polygons),
    )


def _transform(bounds, canvas: int, padding: int):
    min_x, min_y, max_x, max_y = bounds
    width, height = max_x - min_x, max_y - min_y
    if width <= 0 or height <= 0:
        raise ValueError("plan bounds must have positive width and height")
    # Pixel coordinates run through `canvas - 1`; using `canvas` here makes
    # a reflected raster shift by one pixel and defeats canonical fingerprints.
    available = canvas - 1 - 2 * padding
    scale = available / max(width, height)
    x_offset = padding + (available - width * scale) / 2
    y_offset = padding + (available - height * scale) / 2

    def point(x: float, y: float) -> tuple[float, float]:
        return x_offset + (x - min_x) * scale, (canvas - 1) - (y_offset + (y - min_y) * scale)

    return point


def _ring_points(polygon, point) -> list[tuple[float, float]]:
    coords = list(polygon.exterior.coords)
    if len(coords) > 1 and coords[0] == coords[-1]:
        coords.pop()
    return [point(float(x), float(y)) for x, y, *_ in coords]


def _normalized_ring(points: list[tuple[float, float]], canvas: int) -> list[float]:
    """Quantize a rendered ring and reject polygons that collapse at YOLO precision."""
    compact: list[tuple[float, float]] = []
    for x, y in points:
        candidate = (round(x / canvas, 6), round(y / canvas, 6))
        if not compact or candidate != compact[-1]:
            compact.append(candidate)
    if len(compact) > 1 and compact[0] == compact[-1]:
        compact.pop()
    if len(set(compact)) < 3:
        return []
    area = abs(sum(
        x1 * y2 - x2 * y1
        for (x1, y1), (x2, y2) in zip(compact, compact[1:] + compact[:1])
    )) / 2
    if area <= 1e-8:
        return []
    return [coordinate for point in compact for coordinate in point]


def render_plan(plan: dict, *, canvas: int = 768, padding: int | None = None):
    """Return `(PIL image, YOLO label lines)` for one ResPlan geometry plan."""
    from PIL import Image, ImageDraw

    padding = padding if padding is not None else max(8, canvas // 32)
    point = _transform(_plan_bounds(plan), canvas, padding)
    image = Image.new("L", (canvas, canvas), 255)
    draw = ImageDraw.Draw(image)

    for polygon in iter_polygons(plan.get("wall")):
        draw.polygon(_ring_points(polygon, point), fill=0)
        for hole in polygon.interiors:
            draw.polygon([point(float(x), float(y)) for x, y, *_ in hole.coords], fill=255)
    for key, fill, outline in (("door", 255, 0), ("front_door", 255, 0), ("window", 96, 0)):
        for polygon in iter_polygons(plan.get(key)):
            draw.polygon(_ring_points(polygon, point), fill=fill, outline=outline, width=max(1, canvas // 384))

    lines: list[str] = []
    for room_type in SPACE_CLASSES:
        for polygon in iter_polygons(plan.get(room_type)):
            points = _ring_points(polygon, point)
            if len(points) < 3:
                continue
            coords = _normalized_ring(points, canvas)
            if not coords:
                continue
            lines.append(" ".join([str(class_id(room_type)), *(f"{value:.6f}" for value in coords)]))
    return image, lines


def semantic_fingerprint(plan: dict, *, size: int = 64) -> str:
    """Rotation/reflection-invariant quantized semantic-layout fingerprint."""
    bounds = _plan_bounds(plan)
    min_x, min_y, max_x, max_y = bounds
    extent = max(max_x - min_x, max_y - min_y)
    # Use an even inclusive grid (0..size). Midpoints then quantize exactly to
    # size/2 and stay stable under `size - x` reflection.
    grid = size
    x_pad = (extent - (max_x - min_x)) / 2
    y_pad = (extent - (max_y - min_y)) / 2

    def quantize(x, y):
        return (round(((x - min_x + x_pad) / extent) * grid),
                round(((y - min_y + y_pad) / extent) * grid))

    def canonical_ring(points):
        if points and points[0] == points[-1]:
            points = points[:-1]
        if not points:
            return ()
        candidates = []
        for sequence in (points, list(reversed(points))):
            smallest = min(sequence)
            for index, point in enumerate(sequence):
                if point == smallest:
                    candidates.append(tuple(sequence[index:] + sequence[:index]))
        return min(candidates)

    transforms = (
        lambda x, y: (x, y), lambda x, y: (grid - y, x),
        lambda x, y: (grid - x, grid - y), lambda x, y: (y, grid - x),
        lambda x, y: (grid - x, y), lambda x, y: (grid - y, grid - x),
        lambda x, y: (x, grid - y), lambda x, y: (y, x),
    )
    variants = []
    for transform in transforms:
        class_signature = []
        for room_type in SPACE_CLASSES:
            rings = []
            for polygon in iter_polygons(plan.get(room_type)):
                points = [transform(*quantize(float(x), float(y)))
                          for x, y, *_ in polygon.exterior.coords]
                rings.append(canonical_ring(points))
            class_signature.append(tuple(sorted(rings)))
        variants.append(tuple(class_signature))
    canonical = repr(min(variants)).encode()
    return hashlib.sha256(canonical).hexdigest()[:20]


def _image_digest(image) -> str:
    return hashlib.sha256(image.tobytes()).hexdigest()


def convert_resplan_dataset(
    pickle_path: str | Path,
    split_path: str | Path,
    out_dir: str | Path,
    *,
    canvas: int = 768,
    limit_per_split: int | None = None,
) -> dict:
    """Render official canonical splits and remove cross-split layout leakage."""
    if canvas < 128:
        raise ValueError("canvas must be at least 128 pixels")
    plans = load_resplan(pickle_path)
    plan_by_id = {int(plan["id"]): plan for plan in plans}
    split_ids = json.loads(Path(split_path).read_text(encoding="utf-8"))
    out = Path(out_dir)
    for split in ("train", "val", "test"):
        (out / "images" / split).mkdir(parents=True, exist_ok=True)
        (out / "labels" / split).mkdir(parents=True, exist_ok=True)

    summary = {split: 0 for split in ("train", "val", "test")}
    summary.update({"rooms": 0, "dropped_no_rooms": 0, "dropped_cross_split_layout": 0,
                    "dropped_cross_split_image": 0, "excluded_augmented": len(split_ids.get("augmented", []))})
    layout_split: dict[str, str] = {}
    image_split: dict[str, str] = {}
    groups: dict[str, str] = {}

    for split in ("train", "val", "test"):
        candidates = split_ids.get(split, [])
        if limit_per_split is not None:
            candidates = candidates[:limit_per_split]
        for plan_id in candidates:
            plan = plan_by_id.get(int(plan_id))
            if plan is None:
                raise ValueError(f"canonical split references missing plan id {plan_id}")
            image, lines = render_plan(plan, canvas=canvas)
            if not lines:
                summary["dropped_no_rooms"] += 1
                continue
            layout_hash = semantic_fingerprint(plan)
            image_hash = _image_digest(image)
            if layout_hash in layout_split and layout_split[layout_hash] != split:
                summary["dropped_cross_split_layout"] += 1
                continue
            if image_hash in image_split and image_split[image_hash] != split:
                summary["dropped_cross_split_image"] += 1
                continue
            layout_split.setdefault(layout_hash, split)
            image_split.setdefault(image_hash, split)

            stem = f"resplan_{int(plan_id):05d}"
            # Low PNG compression is lossless and keeps dataset construction
            # fast; higher offline compression does not change training pixels.
            image.save(out / "images" / split / f"{stem}.png", format="PNG", compress_level=1)
            (out / "labels" / split / f"{stem}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
            groups[stem] = f"resplan-layout-{layout_hash}"
            summary[split] += 1
            summary["rooms"] += len(lines)

    names = "\n".join(f"  {idx}: {name}" for idx, name in enumerate(SPACE_CLASSES))
    (out / "data.yaml").write_text(
        f"path: .\ntrain: images/train\nval: images/val\ntest: images/test\n"
        f"nc: {len(SPACE_CLASSES)}\nnames:\n{names}\n",
        encoding="utf-8",
    )
    (out / "groups.json").write_text(json.dumps(groups, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "source_metadata.json").write_text(json.dumps({
        "name": "ResPlan", "license": SOURCE_LICENSE, "upstream_commit": UPSTREAM_COMMIT,
        "archive_url": RESPLAN_ARCHIVE_URL, "archive_sha256": RESPLAN_ARCHIVE_SHA256,
        "split_url": RESPLAN_SPLIT_URL, "split_sha256": RESPLAN_SPLIT_SHA256,
        "canonical_augmented_samples_excluded": len(split_ids.get("augmented", [])),
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def build_and_version_resplan(
    source_dir: str | Path,
    out_dir: str | Path,
    *,
    created_at: str,
    canvas: int = 768,
    limit_per_split: int | None = None,
    download: bool = True,
) -> tuple[dict, DatasetVersion]:
    source = prepare_resplan_source(source_dir, download=download)
    summary = convert_resplan_dataset(source["pickle"], source["split"], out_dir,
                                      canvas=canvas, limit_per_split=limit_per_split)
    version = snapshot_dataset(out_dir, name="resplan-spaces-v1", created_at=created_at,
                               class_names=list(SPACE_CLASSES))
    write_version(version, Path(out_dir) / "dataset_version.json")
    return summary, version


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build TakeOff spaces-v1 from official ResPlan")
    parser.add_argument("--source", default="data/resplan/source")
    parser.add_argument("--out", default="data/spaces_v1")
    parser.add_argument("--created-at", required=True, help="ISO8601 dataset version timestamp")
    parser.add_argument("--canvas", type=int, default=768)
    parser.add_argument("--limit-per-split", type=int, default=None, help="small conversion smoke test")
    parser.add_argument("--no-download", action="store_true")
    args = parser.parse_args(argv)
    summary, version = build_and_version_resplan(
        args.source, args.out, created_at=args.created_at, canvas=args.canvas,
        limit_per_split=args.limit_per_split, download=not args.no_download,
    )
    print(f"[resplan] {summary}")
    print(f"[resplan] dataset version {version.id} -> {args.out}/dataset_version.json")
    print(f"[resplan] validate: python -m ml.datasets.validate_spaces --data {args.out}/data.yaml --require-groups")
    return 0 if summary["train"] and summary["val"] and summary["test"] else 1


if __name__ == "__main__":
    sys.exit(main())
