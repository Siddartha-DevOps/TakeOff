"""
CubiCasa5K → versioned YOLO-seg dataset (Phase 2: Dataset v1).

CubiCasa5K (Kalervo et al., 2019; CC-BY-4.0, hosted on Zenodo record 2613548) is
5000 annotated residential floor plans. Each sample folder contains a floor-plan
raster (``F1_original.png`` / ``F1_scaled.png``) and a ``model.svg`` whose
``<g class="Space <RoomType>">`` groups carry the room polygons. This module
turns those into the trainer's format by reusing the existing space-class remap
(``bootstrap_public``) and content-addressed versioning (``versioning``).

Split of responsibilities:
- **Pure / tested here**: SVG polygon parsing, PNG dimension reading (stdlib
  struct — no PIL), sample → YOLO label lines, dataset write, versioning.
- **Orchestration (run on the data box)**: ``download_cubicasa`` fetches the
  multi-GB archive over the network; this repo/CI never downloads it.

No heavy deps — stdlib + the existing ``ml.datasets`` helpers.
"""

from __future__ import annotations

import argparse
import os
import shutil
import struct
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable, Optional

from .bootstrap_public import (
    CUBICASA_TO_TAKEOFF,
    build_label_lines,
    data_yaml_text,
    remap_label,
)
from .versioning import DatasetVersion, snapshot_dataset, write_version

CUBICASA_ZENODO_URL = "https://zenodo.org/record/2613548/files/cubicasa5k.zip"


# --------------------------------------------------------------------------- #
# Pure parsers (stdlib) — unit-tested.
# --------------------------------------------------------------------------- #
def svg_polygon_points(points_attr: str) -> list[list[float]]:
    """Parse an SVG ``points="x1,y1 x2,y2 ..."`` attribute to ``[[x, y], ...]``.

    Tolerates comma- or whitespace-separated coordinate pairs (both appear in
    the wild). Malformed trailing tokens are skipped, not fatal.
    """
    raw = points_attr.replace(",", " ").split()
    coords: list[float] = []
    for tok in raw:
        try:
            coords.append(float(tok))
        except ValueError:
            continue
    return [[coords[i], coords[i + 1]] for i in range(0, len(coords) - 1, 2)]


def _local(tag: str) -> str:
    """Strip an XML namespace: '{http://www.w3.org/2000/svg}g' -> 'g'."""
    return tag.rsplit("}", 1)[-1]


def parse_cubicasa_svg(svg_text: str) -> list[tuple[str, list[list[float]]]]:
    """Extract ``(room_label, pixel_ring)`` pairs from a CubiCasa ``model.svg``.

    Rooms are ``<g class="Space <RoomType> ...">`` groups; the room type is the
    class token after ``Space``. Each such group's child ``<polygon>`` supplies
    the ring. Non-space groups (Wall, Door, Window, ...) are returned with their
    raw label too — the caller's remap drops anything not in the space vocab, so
    this parser stays format-faithful and the vocabulary lives in one place.
    """
    try:
        root = ET.fromstring(svg_text)
    except ET.ParseError:
        return []

    out: list[tuple[str, list[list[float]]]] = []
    for g in root.iter():
        if _local(g.tag) != "g":
            continue
        classes = (g.get("class") or "").split()
        if not classes:
            continue
        # Room groups look like class="Space LivingRoom"; take the type token.
        if classes[0] == "Space" and len(classes) >= 2:
            label = classes[1]
        else:
            label = classes[0]
        for child in g:
            if _local(child.tag) == "polygon" and child.get("points"):
                ring = svg_polygon_points(child.get("points"))
                if len(ring) >= 3:
                    out.append((label, ring))
    return out


def png_dimensions(path: os.PathLike | str) -> tuple[int, int]:
    """Read (width, height) from a PNG's IHDR header via struct — no PIL/cv2."""
    with open(path, "rb") as f:
        header = f.read(24)
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"not a PNG file: {path}")
    width, height = struct.unpack(">II", header[16:24])
    return int(width), int(height)


# --------------------------------------------------------------------------- #
# Conversion + versioning (filesystem; testable on a synthetic fixture).
# --------------------------------------------------------------------------- #
def _find_sample(sample_dir: Path) -> Optional[tuple[Path, Path]]:
    """Return (svg_path, image_path) for a CubiCasa sample dir, or None."""
    svg = sample_dir / "model.svg"
    if not svg.is_file():
        return None
    for img_name in ("F1_original.png", "F1_scaled.png", "F1.png"):
        img = sample_dir / img_name
        if img.is_file():
            return svg, img
    return None


def iter_sample_dirs(root: Path) -> Iterable[Path]:
    """Yield sample directories under a CubiCasa root (those containing model.svg)."""
    for svg in sorted(Path(root).rglob("model.svg")):
        yield svg.parent


def convert_cubicasa_dataset(
    root: os.PathLike | str,
    out_dir: os.PathLike | str,
    *,
    val_every: int = 5,
    mapping: Optional[dict] = None,
    limit: Optional[int] = None,
) -> dict:
    """Convert an extracted CubiCasa5K tree into a YOLO-seg dataset directory.

    Writes ``images/{train,val}`` (copied PNGs) + ``labels/{train,val}`` (YOLO-seg
    txt) + ``data.yaml``. Samples whose rooms all fall outside the space vocab are
    skipped (counted in ``dropped``). Every ``val_every``-th kept sample → val.
    Returns a summary dict.
    """
    root = Path(root)
    out = Path(out_dir)
    for split in ("train", "val"):
        (out / f"images/{split}").mkdir(parents=True, exist_ok=True)
        (out / f"labels/{split}").mkdir(parents=True, exist_ok=True)

    summary = {"train": 0, "val": 0, "rooms": 0, "dropped": 0, "skipped_no_image": 0}
    kept = 0
    for sample_dir in iter_sample_dirs(root):
        if limit is not None and kept >= limit:
            break
        found = _find_sample(sample_dir)
        if not found:
            summary["skipped_no_image"] += 1
            continue
        svg_path, img_path = found
        try:
            w, h = png_dimensions(img_path)
        except ValueError:
            summary["skipped_no_image"] += 1
            continue

        rooms = parse_cubicasa_svg(svg_path.read_text())
        lines = build_label_lines(rooms, w, h, mapping if mapping is not None else CUBICASA_TO_TAKEOFF)
        if not lines:
            summary["dropped"] += 1
            continue

        split = "val" if (kept % val_every == 0) else "train"
        stem = sample_dir.name or f"sample_{kept}"
        shutil.copyfile(img_path, out / f"images/{split}/{stem}.png")
        (out / f"labels/{split}/{stem}.txt").write_text("\n".join(lines))
        summary[split] += 1
        summary["rooms"] += len(lines)
        kept += 1

    (out / "data.yaml").write_text(data_yaml_text(out))
    return summary


def build_and_version_cubicasa(
    root: os.PathLike | str,
    out_dir: os.PathLike | str,
    *,
    created_at: str,
    parent: Optional[str] = None,
    val_every: int = 5,
    limit: Optional[int] = None,
) -> tuple[dict, DatasetVersion]:
    """Convert + snapshot: produces the dataset AND a content-addressed version.

    ``created_at`` is an injected ISO8601 string (the versioning layer never calls
    the wall clock). Writes ``dataset_version.json`` next to the data.
    """
    from .bootstrap_public import SPACE_CLASSES

    summary = convert_cubicasa_dataset(root, out_dir, val_every=val_every, limit=limit)
    version = snapshot_dataset(
        out_dir, name="cubicasa-spaces", created_at=created_at,
        class_names=list(SPACE_CLASSES), parent=parent,
    )
    write_version(version, Path(out_dir) / "dataset_version.json")
    return summary, version


# --------------------------------------------------------------------------- #
# Download orchestration (data box only — not run in CI).
# --------------------------------------------------------------------------- #
def download_cubicasa(dest: os.PathLike | str, *, url: str = CUBICASA_ZENODO_URL) -> Path:
    """Download the CubiCasa5K archive (~5 GB) to ``dest``. Run on the data box.

    Kept dependency-free (urllib) and streamed to disk. Not exercised in CI —
    the network fetch is orchestration; the conversion above is what's tested.
    """
    import urllib.request

    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url) as resp, open(dest, "wb") as f:  # noqa: S310 (trusted Zenodo URL)
        shutil.copyfileobj(resp, f)
    return dest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Convert CubiCasa5K to a versioned YOLO-seg dataset")
    ap.add_argument("--root", required=True, help="path to an extracted CubiCasa5K tree")
    ap.add_argument("--out", required=True, help="output dataset directory")
    ap.add_argument("--created-at", required=True, help="ISO8601 timestamp for the DatasetVersion")
    ap.add_argument("--val-every", type=int, default=5)
    ap.add_argument("--limit", type=int, default=None, help="cap samples (smoke runs)")
    args = ap.parse_args(argv)

    summary, version = build_and_version_cubicasa(
        args.root, args.out, created_at=args.created_at,
        val_every=args.val_every, limit=args.limit,
    )
    print(f"[cubicasa] {summary}")
    print(f"[cubicasa] dataset version {version.id} (train={version.splits.get('train', 0)}, "
          f"val={version.splits.get('val', 0)}) -> {args.out}/dataset_version.json")
    print(f"[cubicasa] validate with: python -m ml.preflight --data {args.out}/data.yaml --require train")
    return 0 if (summary["train"] + summary["val"]) > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
