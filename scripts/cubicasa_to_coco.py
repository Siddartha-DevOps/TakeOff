"""Convert CubiCasa5K SVG annotations to COCO instance segmentation format."""
import json, os, glob
import numpy as np
from PIL import Image
import xml.etree.ElementTree as ET

ROOM_CLASSES = [
    "Background", "Outdoor", "Wall", "Kitchen", "Living Room",
    "Bedroom", "Bath", "Hallway", "Railing", "Storage", "Garage", "Other"
]

def parse_svg_polygons(svg_path):
    """Extract room polygons from CubiCasa SVG."""
    tree = ET.parse(svg_path)
    root = tree.getroot()
    ns = {'svg': 'http://www.w3.org/2000/svg'}

    rooms = []
    for polygon in root.findall('.//svg:polygon', ns):
        points_str = polygon.get('points', '')
        class_name = polygon.get('class', 'Other')

        points = []
        for pair in points_str.strip().split():
            x, y = pair.split(',')
            points.extend([float(x), float(y)])

        if len(points) >= 6:  # at least 3 vertices
            rooms.append({
                "segmentation": [points],
                "category": class_name,
            })
    return rooms

def build_coco_dataset(cubicasa_root, output_path):
    coco = {
        "images": [],
        "annotations": [],
        "categories": [{"id": i, "name": n} for i, n in enumerate(ROOM_CLASSES)]
    }

    ann_id = 0
    for img_id, folder in enumerate(sorted(glob.glob(f"{cubicasa_root}/*/"))):
        img_path = os.path.join(folder, "F1_scaled.png")
        svg_path = os.path.join(folder, "model.svg")

        if not (os.path.exists(img_path) and os.path.exists(svg_path)):
            continue

        img = Image.open(img_path)
        w, h = img.size

        coco["images"].append({
            "id": img_id, "file_name": img_path,
            "width": w, "height": h
        })

        for room in parse_svg_polygons(svg_path):
            cat_name = room["category"]
            cat_id = next(
                (c["id"] for c in coco["categories"] if c["name"].lower() == cat_name.lower()),
                len(ROOM_CLASSES) - 1  # fallback to "Other"
            )

            seg = room["segmentation"][0]
            xs = seg[0::2]
            ys = seg[1::2]
            bbox = [min(xs), min(ys), max(xs)-min(xs), max(ys)-min(ys)]

            coco["annotations"].append({
                "id": ann_id, "image_id": img_id,
                "category_id": cat_id,
                "segmentation": room["segmentation"],
                "bbox": bbox, "area": bbox[2]*bbox[3],
                "iscrowd": 0
            })
            ann_id += 1

    with open(output_path, 'w') as f:
        json.dump(coco, f)
    print(f"Created {len(coco['images'])} images, {ann_id} annotations")

if __name__ == "__main__":
    build_coco_dataset("CubiCasa5k/", "datasets/cubicasa_coco.json")
