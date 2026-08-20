"""
Convert SESYD/CubiCasa-icon Pascal-VOC-style symbol annotations to YOLO
detection format, for training the Model 2 symbol/object detector (see
objects_dataset.py for the class list + data.yaml writer).

Expected source layout — one Pascal-VOC XML sitting next to each PNG:

    SESYD/floorplans/**/plan_0001.xml
    SESYD/floorplans/**/plan_0001.png

Each XML is walked for <object><name>...</name><bndbox>...</bndbox></object>
entries; entries whose <name> isn't in objects_dataset.SYMBOL_CLASSES are
dropped (SESYD's full vocabulary is broader than the fixtures this app
tracks). Output is a flat YOLO detection dataset:

    datasets/symbols_yolo/images/*.png   (symlinked to the source images)
    datasets/symbols_yolo/labels/*.txt   (class cx cy w h, normalized)

This is a flat pool, not yet split into train/val — run e.g.
`ultralytics.data.utils.autosplit` (or your own split) before training with
train_yolov8_objects.py / modal_gpu_objects.py.

Usage
-----
    python training/sesyd_to_yolo.py --sesyd-root SESYD/floorplans --output datasets/symbols_yolo
"""

from __future__ import annotations

import sys
from pathlib import Path

# Import the sibling pure-Python module by path rather than relying on the
# caller's sys.path / package context (mirrors modal_gpu.py's convention).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from objects_dataset import SYMBOL_CLASSES, bbox_to_yolo_line  # noqa: E402


def parse_sesyd_objects(xml_path: str | Path) -> list[dict]:
    """Parse one Pascal-VOC-style annotation XML into `{"name", "bbox"}` dicts.

    Skips any <object> missing a name or a well-formed <bndbox> rather than
    raising — source annotation sets like SESYD are not perfectly clean.
    """
    import xml.etree.ElementTree as ET

    tree = ET.parse(xml_path)
    root = tree.getroot()

    objects = []
    for obj in root.findall(".//object"):
        name_el = obj.find("name")
        bbox_el = obj.find("bndbox")
        if name_el is None or name_el.text is None or bbox_el is None:
            continue
        try:
            xmin = float(bbox_el.find("xmin").text)
            ymin = float(bbox_el.find("ymin").text)
            xmax = float(bbox_el.find("xmax").text)
            ymax = float(bbox_el.find("ymax").text)
        except (AttributeError, TypeError, ValueError):
            continue
        objects.append({"name": name_el.text.strip().lower(), "bbox": (xmin, ymin, xmax, ymax)})
    return objects


def sesyd_to_yolo(sesyd_root: str | Path, output_dir: str | Path) -> dict:
    """Walk `sesyd_root` for XML/PNG pairs and write a flat YOLO detection dataset.

    Returns a summary dict `{"images", "boxes", "skipped"}`. Safe to re-run —
    existing image symlinks are left alone instead of raising FileExistsError.
    """
    from PIL import Image  # lazy: keeps this module importable without Pillow

    sesyd_root = Path(sesyd_root)
    output_dir = Path(output_dir)
    images_dir = output_dir / "images"
    labels_dir = output_dir / "labels"
    images_dir.mkdir(parents=True, exist_ok=True)
    labels_dir.mkdir(parents=True, exist_ok=True)

    n_images = n_boxes = n_skipped = 0

    for xml_file in sorted(sesyd_root.rglob("*.xml")):
        img_file = xml_file.with_suffix(".png")
        if not img_file.exists():
            n_skipped += 1
            continue

        with Image.open(img_file) as img:
            w, h = img.size

        lines = []
        for obj in parse_sesyd_objects(xml_file):
            name = obj["name"]
            if name not in SYMBOL_CLASSES:
                continue
            cls_id = SYMBOL_CLASSES.index(name)
            xmin, ymin, xmax, ymax = obj["bbox"]
            lines.append(bbox_to_yolo_line(cls_id, xmin, ymin, xmax, ymax, w, h))

        if not lines:
            n_skipped += 1
            continue

        base = img_file.stem
        (labels_dir / f"{base}.txt").write_text("\n".join(lines))

        dest_img = images_dir / f"{base}.png"
        if not dest_img.exists():
            dest_img.symlink_to(img_file.resolve())

        n_images += 1
        n_boxes += len(lines)

    return {"images": n_images, "boxes": n_boxes, "skipped": n_skipped}


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Convert SESYD/CubiCasa icon annotations to YOLO detection format")
    ap.add_argument("--sesyd-root", required=True, help="Directory tree of *.xml/*.png annotation pairs")
    ap.add_argument("--output", default="datasets/symbols_yolo")
    args = ap.parse_args()

    summary = sesyd_to_yolo(args.sesyd_root, args.output)
    print(f"[sesyd_to_yolo] {summary}")


if __name__ == "__main__":
    main()
