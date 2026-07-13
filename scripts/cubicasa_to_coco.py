#!/usr/bin/env python3
"""
TakeOff.ai — CubiCasa5K -> COCO + YOLO converter.

CubiCasa5K (Aalto University; github.com/CubiCasa/CubiCasa5k) ships
annotations as SVG, not COCO/YOLO, and its own class taxonomy doesn't line
up 1:1 with datasets/rooms.yaml or datasets/symbols.yaml. This script
parses each sample's model.svg, maps CubiCasa's classes onto ours via the
tables below, and writes both a COCO instance-segmentation JSON (rooms
only — COCO segmentation is polygon-based) and YOLO-format label .txt
files into the train/val/test/images+labels layout that rooms.yaml and
symbols.yaml expect. Symbol labels default to YOLOv8-seg polygon format
(--symbols-format polygon) so the output is directly consumable by
app/backend/training/train_yolov8_seg.py, which already trains symbols
as task="segment"; pass --symbols-format bbox for plain YOLOv8-detect
training against symbols.yaml standalone instead.

Expected input layout (standard CubiCasa5K release):
    <root>/
      high_quality_architectural/<id>/model.svg, F1_scaled.png
      high_quality/<id>/model.svg, F1_scaled.png
      colorful/<id>/model.svg, F1_scaled.png
      train.txt  val.txt  test.txt   # each line: "high_quality_architectural/<id>"

Honest scope limits (read before trusting the output blindly):
  - CubiCasa5K's icon layer has generic "Door" / "Window" groups, not our
    5-way subtype split (standard/bifold/sliding/double/pocket door;
    fixed/casement/sliding/transom/bay window). Every door is emitted as
    standard_door and every window as fixed_window — subtype refinement
    needs either extra geometry heuristics or a separate labeling pass,
    not fabricated here.
  - CubiCasa5K has no electrical symbols (outlet/switch/light_fixture/
    smoke_detector) at all — it's a plumbing/architectural dataset. This
    script only ever emits the 4 plumbing symbol classes; a separate MEP
    dataset is required for the electrical half of symbols.yaml, per
    AI_TRAINING_GUIDE.md Feature 5's own "2,000 floor plans with MEP
    annotations" being a distinct dataset requirement from room detection.
  - Any CubiCasa <g class="..."> value not present in the mapping tables
    below is counted and logged at the end, never silently dropped into
    a wrong bucket — extend the tables if the summary shows meaningful
    unmapped volume.

Usage:
    python scripts/cubicasa_to_coco.py \
        --cubicasa-root /data/cubicasa5k \
        --output-dir /data \
        --format both        # coco | yolo | both

Output:
    <output-dir>/rooms/{train,val,test}/{images,labels}/...      # split-first, matches datasets/rooms.yaml
    <output-dir>/symbols/{images,labels}/{train,val,test}/...    # images-first, matches datasets/symbols.yaml
                                                                   # and train_yolov8_seg.py's own layout
    <output-dir>/rooms/coco_rooms_{train,val,test}.json   (--format coco/both)
"""

import argparse
import json
import logging
import shutil
import sys
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("cubicasa_to_coco")

SVG_NS = {"svg": "http://www.w3.org/2000/svg"}

# ── Class taxonomies (must match datasets/rooms.yaml / datasets/symbols.yaml) ──
ROOM_CLASSES = [
    "living", "bedroom", "kitchen", "bathroom",
    "dining", "office", "hallway", "closet", "utility",
]
SYMBOL_CLASSES = [
    "standard_door", "bifold_door", "sliding_door", "double_door", "pocket_door",
    "fixed_window", "casement_window", "sliding_window", "transom_window", "bay_window",
    "toilet", "sink", "shower", "bathtub",
    "outlet", "switch", "light_fixture", "smoke_detector",
]

# CubiCasa5K "Space <RoomType>" suffix -> our room class. CubiCasa's own
# taxonomy is finer-grained than ours; anything not listed here is logged
# as unmapped rather than guessed at.
ROOM_CLASS_MAP = {
    "LivingRoom": "living", "Lounge": "living", "Ballroom": "living",
    "Bedroom": "bedroom", "DressingRoom": "bedroom",
    "Kitchen": "kitchen",
    "Bathroom": "bathroom", "PowderRoom": "bathroom", "Sauna": "bathroom",
    "DiningRoom": "dining",
    "Office": "office", "Library": "office",
    "Hall": "hallway", "HallWay": "hallway", "EntranceHall": "hallway",
    "DraughtLobby": "hallway", "PassageWay": "hallway",
    "Closet": "closet", "WalkInCloset": "closet", "Wardrobe": "closet",
    "UtilityRoom": "utility", "BoilerRoom": "utility", "TechnicalRoom": "utility",
    "GarbageShed": "utility", "Garage": "utility", "Storage": "utility",
    "Pipeshaft": "utility", "ElevatorShaft": "utility",
}

# CubiCasa5K icon group class -> our plumbing symbol class.
PLUMBING_ICON_MAP = {
    "Toilet": "toilet",
    "Sink": "sink", "Washbasin": "sink",
    "Shower": "shower",
    "Bathtub": "bathtub", "Tub": "bathtub",
}

DEFAULT_DOOR_CLASS = "standard_door"
DEFAULT_WINDOW_CLASS = "fixed_window"


def _find_dataset_root_dirs(root: Path):
    """CubiCasa5K ships 3 quality tiers as sibling dirs under the root."""
    for tier in ("high_quality_architectural", "high_quality", "colorful"):
        d = root / tier
        if d.is_dir():
            yield d


def _read_split_file(root: Path, name: str) -> list:
    split_path = root / f"{name}.txt"
    if not split_path.exists():
        return []
    lines = [ln.strip() for ln in split_path.read_text().splitlines() if ln.strip()]
    return [root / ln for ln in lines]


def discover_samples(root: Path) -> dict:
    """
    Returns {"train": [sample_dir, ...], "val": [...], "test": [...]}.
    Prefers CubiCasa5K's own train.txt/val.txt/test.txt; falls back to a
    deterministic 80/10/10 split over every sample folder found so the
    script still works against mirrors that don't ship split files.
    """
    splits = {name: _read_split_file(root, name) for name in ("train", "val", "test")}
    if any(splits.values()):
        for name, paths in splits.items():
            splits[name] = [p for p in paths if (p / "model.svg").exists()]
        return splits

    logger.warning("No train.txt/val.txt/test.txt found under %s — falling back to an 80/10/10 split", root)
    all_samples = sorted(
        d for tier_dir in _find_dataset_root_dirs(root)
        for d in tier_dir.iterdir()
        if d.is_dir() and (d / "model.svg").exists()
    )
    n = len(all_samples)
    n_train, n_val = int(n * 0.8), int(n * 0.1)
    return {
        "train": all_samples[:n_train],
        "val": all_samples[n_train:n_train + n_val],
        "test": all_samples[n_train + n_val:],
    }


def _local_tag(elem) -> str:
    return elem.tag.rsplit("}", 1)[-1]


def _classes_of(elem) -> list:
    return (elem.get("class") or "").split()


def _parse_points(polygon_elem) -> list:
    raw = polygon_elem.get("points", "")
    points = []
    for pair in raw.strip().split():
        try:
            x_str, y_str = pair.split(",")
            points.append((float(x_str), float(y_str)))
        except ValueError:
            continue
    return points


def _bbox_of_points(points: list) -> tuple:
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def parse_svg(svg_path: Path, unmapped_counter: Counter) -> dict:
    """
    Returns {"rooms": [{"class": str, "points": [(x,y),...]}],
              "doors": [{"class": str, "points": [(x,y),...]}],
              "windows": [...], "plumbing": [...]}
    Coordinates are in the SVG's own user-space units, matched 1:1 against
    F1_scaled.png (CubiCasa5K scales the SVG viewBox to that image).
    """
    result = {"rooms": [], "doors": [], "windows": [], "plumbing": []}
    tree = ET.parse(str(svg_path))
    root = tree.getroot()

    for g in root.iter():
        if _local_tag(g) != "g":
            continue
        classes = _classes_of(g)
        if not classes:
            continue

        polygon = None
        for child in g:
            if _local_tag(child) == "polygon":
                polygon = child
                break
        if polygon is None:
            continue
        points = _parse_points(polygon)
        if len(points) < 3:
            continue

        if classes[0] == "Space" and len(classes) > 1:
            mapped = ROOM_CLASS_MAP.get(classes[1])
            if mapped:
                result["rooms"].append({"class": mapped, "points": points})
            else:
                unmapped_counter[f"Space:{classes[1]}"] += 1
        elif "Door" in classes:
            result["doors"].append({"class": DEFAULT_DOOR_CLASS, "points": points})
        elif "Window" in classes:
            result["windows"].append({"class": DEFAULT_WINDOW_CLASS, "points": points})
        else:
            mapped = None
            for c in classes:
                mapped = PLUMBING_ICON_MAP.get(c)
                if mapped:
                    break
            if mapped:
                result["plumbing"].append({"class": mapped, "points": points})
            else:
                unmapped_counter[":".join(classes)] += 1

    return result


def _image_size(sample_dir: Path):
    from PIL import Image
    for name in ("F1_scaled.png", "F1_original.png"):
        p = sample_dir / name
        if p.exists():
            with Image.open(p) as im:
                return p, im.size  # (width, height)
    return None, None


def write_yolo_seg_label(path: Path, items: list, class_list: list, width: int, height: int):
    """
    YOLOv8-seg polygon label format: "cls x1 y1 x2 y2 ...". Used for both
    rooms and symbols — app/backend/training/train_yolov8_seg.py trains
    symbols as segmentation (task="segment") too, not plain bbox detection,
    and a CubiCasa icon's 4-corner rectangle polygon carries strictly more
    information than its bbox, so there's no format-specific data loss in
    sharing this writer.
    """
    lines = []
    for item in items:
        cls_id = class_list.index(item["class"])
        coords = []
        for x, y in item["points"]:
            coords.append(f"{x / width:.6f}")
            coords.append(f"{y / height:.6f}")
        lines.append(f"{cls_id} " + " ".join(coords))
    path.write_text("\n".join(lines) + ("\n" if lines else ""))


def write_yolo_bbox_label(path: Path, symbols: list, class_list: list, width: int, height: int):
    """Plain YOLOv8-detect bbox format — kept for callers training a bbox-only detector against symbols.yaml directly rather than through train_yolov8_seg.py."""
    lines = []
    for sym in symbols:
        cls_id = class_list.index(sym["class"])
        x1, y1, x2, y2 = _bbox_of_points(sym["points"])
        cx, cy = (x1 + x2) / 2 / width, (y1 + y2) / 2 / height
        w, h = (x2 - x1) / width, (y2 - y1) / height
        lines.append(f"{cls_id} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")
    path.write_text("\n".join(lines) + ("\n" if lines else ""))


def convert(cubicasa_root: Path, output_dir: Path, fmt: str, splits_wanted: list, symbols_format: str = "polygon"):
    unmapped = Counter()
    coco_accum = {name: {"images": [], "annotations": [], "next_img_id": 1, "next_ann_id": 1} for name in splits_wanted}

    splits = discover_samples(cubicasa_root)

    for split_name in splits_wanted:
        samples = splits.get(split_name, [])
        logger.info("Split '%s': %d samples", split_name, len(samples))

        # rooms: split-first (train/images/...), matches datasets/rooms.yaml.
        # symbols: images-first (images/train/...), matches datasets/symbols.yaml
        # *and* app/backend/training/train_yolov8_seg.py's build_data_yaml().
        rooms_img_dir = output_dir / "rooms" / split_name / "images"
        rooms_lbl_dir = output_dir / "rooms" / split_name / "labels"
        symbols_img_dir = output_dir / "symbols" / "images" / split_name
        symbols_lbl_dir = output_dir / "symbols" / "labels" / split_name
        for d in (rooms_img_dir, rooms_lbl_dir, symbols_img_dir, symbols_lbl_dir):
            d.mkdir(parents=True, exist_ok=True)

        for i, sample_dir in enumerate(samples):
            svg_path = sample_dir / "model.svg"
            try:
                parsed = parse_svg(svg_path, unmapped)
            except ET.ParseError as e:
                logger.warning("Skipping %s — unparseable SVG: %s", svg_path, e)
                continue

            img_path, size = _image_size(sample_dir)
            if img_path is None:
                logger.warning("Skipping %s — no F1_scaled.png/F1_original.png", sample_dir)
                continue
            width, height = size

            stem = f"{sample_dir.parent.name}_{sample_dir.name}"
            image_filename = f"{stem}{img_path.suffix}"

            if parsed["rooms"]:
                shutil.copy(img_path, rooms_img_dir / image_filename)
                if fmt in ("yolo", "both"):
                    write_yolo_seg_label(rooms_lbl_dir / f"{stem}.txt", parsed["rooms"], ROOM_CLASSES, width, height)
                if fmt in ("coco", "both"):
                    acc = coco_accum[split_name]
                    img_id = acc["next_img_id"]
                    acc["images"].append({"id": img_id, "file_name": image_filename, "width": width, "height": height})
                    acc["next_img_id"] += 1
                    for room in parsed["rooms"]:
                        flat = [c for xy in room["points"] for c in xy]
                        x1, y1, x2, y2 = _bbox_of_points(room["points"])
                        acc["annotations"].append({
                            "id": acc["next_ann_id"],
                            "image_id": img_id,
                            "category_id": ROOM_CLASSES.index(room["class"]),
                            "segmentation": [flat],
                            "bbox": [x1, y1, x2 - x1, y2 - y1],
                            "area": (x2 - x1) * (y2 - y1),
                            "iscrowd": 0,
                        })
                        acc["next_ann_id"] += 1

            symbols = parsed["doors"] + parsed["windows"] + parsed["plumbing"]
            if symbols:
                shutil.copy(img_path, symbols_img_dir / image_filename)
                if fmt in ("yolo", "both"):
                    if symbols_format == "polygon":
                        write_yolo_seg_label(symbols_lbl_dir / f"{stem}.txt", symbols, SYMBOL_CLASSES, width, height)
                    else:
                        write_yolo_bbox_label(symbols_lbl_dir / f"{stem}.txt", symbols, SYMBOL_CLASSES, width, height)

            if (i + 1) % 200 == 0:
                logger.info("  ... %d/%d", i + 1, len(samples))

        if fmt in ("coco", "both"):
            acc = coco_accum[split_name]
            coco_json = {
                "images": acc["images"],
                "annotations": acc["annotations"],
                "categories": [{"id": idx, "name": name} for idx, name in enumerate(ROOM_CLASSES)],
            }
            out_path = output_dir / "rooms" / f"coco_rooms_{split_name}.json"
            out_path.write_text(json.dumps(coco_json))
            logger.info("Wrote %s (%d images, %d annotations)", out_path, len(acc["images"]), len(acc["annotations"]))

    if unmapped:
        logger.warning("Unmapped CubiCasa classes encountered (extend the mapping tables if volume is significant):")
        for cls, count in unmapped.most_common(20):
            logger.warning("  %6d  %s", count, cls)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cubicasa-root", required=True, type=Path, help="Path to the extracted CubiCasa5K dataset")
    parser.add_argument("--output-dir", required=True, type=Path, help="Where to write rooms/ and symbols/ output trees")
    parser.add_argument("--format", choices=["coco", "yolo", "both"], default="both")
    parser.add_argument("--splits", default="train,val,test", help="Comma-separated splits to convert")
    parser.add_argument(
        "--symbols-format", choices=["polygon", "bbox"], default="polygon",
        help="polygon (default) matches app/backend/training/train_yolov8_seg.py's YOLOv8-seg labels; "
             "bbox is plain YOLOv8-detect, for training directly against datasets/symbols.yaml as a detector.",
    )
    args = parser.parse_args()

    if not args.cubicasa_root.is_dir():
        logger.error("--cubicasa-root %s does not exist", args.cubicasa_root)
        sys.exit(1)

    convert(args.cubicasa_root, args.output_dir, args.format, args.splits.split(","), args.symbols_format)


if __name__ == "__main__":
    main()
