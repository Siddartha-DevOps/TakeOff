"""Convert COCO to YOLO-seg format (one .txt per image with normalized polygon coords)."""
import json, os
from PIL import Image

def coco_to_yolo_seg(coco_json, images_dir, output_dir):
    os.makedirs(f"{output_dir}/labels", exist_ok=True)
    os.makedirs(f"{output_dir}/images", exist_ok=True)

    with open(coco_json) as f:
        coco = json.load(f)

    img_lookup = {img["id"]: img for img in coco["images"]}

    # Group annotations by image
    from collections import defaultdict
    anns_by_img = defaultdict(list)
    for ann in coco["annotations"]:
        anns_by_img[ann["image_id"]].append(ann)

    for img_id, img_info in img_lookup.items():
        w, h = img_info["width"], img_info["height"]
        lines = []

        for ann in anns_by_img.get(img_id, []):
            cls = ann["category_id"]
            seg = ann["segmentation"][0]
            # Normalize to 0-1
            normalized = []
            for i in range(0, len(seg), 2):
                normalized.append(f"{seg[i]/w:.6f}")
                normalized.append(f"{seg[i+1]/h:.6f}")
            lines.append(f"{cls} " + " ".join(normalized))

        label_file = os.path.splitext(os.path.basename(img_info["file_name"]))[0] + ".txt"
        with open(f"{output_dir}/labels/{label_file}", 'w') as f:
            f.write("\n".join(lines))

        # Symlink or copy image
        os.symlink(
            os.path.abspath(img_info["file_name"]),
            f"{output_dir}/images/{os.path.basename(img_info['file_name'])}"
        )

coco_to_yolo_seg("datasets/cubicasa_coco.json", "CubiCasa5k/", "datasets/rooms_yolo/")
