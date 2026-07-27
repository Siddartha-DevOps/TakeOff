"""Render YOLO-seg labels over their images — a visual sanity check.

Near-zero training mAP usually means the labels don't line up with the pixels
(a coordinate-space / resolution mismatch in conversion), not that the model
needs longer. This draws each label polygon back onto its image so you can *see*
whether the room outlines sit on the rooms. If they do, the labels are good and
accuracy is a training-config problem; if they're shifted or scaled, the dataset
conversion is the bug.

Pure + dependency-light: reads the YOLO-seg txt (class + normalized ring),
denormalizes against the image's own size, draws with Pillow. No torch/cv2.

    python -m ml.datasets.preview_labels --dataset data/spaces_v1 --split train \
        --n 8 --out label_previews
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .bootstrap_public import SPACE_CLASSES

# 7 distinct outline colors, one per space class (index == class id).
_COLORS = [
    (230, 25, 75), (60, 180, 75), (0, 130, 200), (245, 130, 48),
    (145, 30, 180), (70, 240, 240), (240, 50, 230),
]


def _parse_label_line(line: str) -> tuple[int, list[tuple[float, float]]]:
    """'cls x1 y1 x2 y2 ...' (normalized) -> (class_id, [(x, y)...] normalized)."""
    parts = line.split()
    cls = int(float(parts[0]))
    xy = [float(v) for v in parts[1:]]
    ring = [(xy[i], xy[i + 1]) for i in range(0, len(xy) - 1, 2)]
    return cls, ring


def render_split(dataset_dir: Path, split: str, n: int, out_dir: Path) -> list[Path]:
    """Overlay labels on the first ``n`` images of a split; return written paths."""
    from PIL import Image, ImageDraw

    ds = Path(dataset_dir)
    img_dir = ds / "images" / split
    lbl_dir = ds / "labels" / split
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    images = sorted(p for p in img_dir.iterdir() if p.suffix.lower() == ".png")
    written: list[Path] = []
    for img_path in images[:n]:
        label_path = lbl_dir / f"{img_path.stem}.txt"
        if not label_path.is_file():
            continue
        img = Image.open(img_path).convert("RGB")
        w, h = img.size
        draw = ImageDraw.Draw(img)
        n_polys = 0
        for line in label_path.read_text().splitlines():
            if not line.strip():
                continue
            cls, ring = _parse_label_line(line)
            if len(ring) < 3:
                continue
            pts = [(x * w, y * h) for x, y in ring]  # denormalize to this image
            color = _COLORS[cls % len(_COLORS)]
            draw.line(pts + [pts[0]], fill=color, width=3)  # closed outline
            label = SPACE_CLASSES[cls] if cls < len(SPACE_CLASSES) else str(cls)
            draw.text(pts[0], label, fill=color)
            n_polys += 1
        dest = out_dir / f"{img_path.stem}__{n_polys}rooms.png"
        img.save(dest)
        written.append(dest)
        print(f"[preview] {dest.name}  ({w}x{h}, {n_polys} rooms)")
    return written


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Draw YOLO-seg labels over their images")
    ap.add_argument("--dataset", required=True, help="dataset dir (images/ + labels/)")
    ap.add_argument("--split", default="train")
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--out", default="label_previews")
    args = ap.parse_args(argv)

    written = render_split(Path(args.dataset), args.split, args.n, Path(args.out))
    if not written:
        print("[preview] no images written — check dataset path/split")
        return 1
    print(f"[preview] wrote {len(written)} overlays to {args.out}/ — open them and "
          "confirm the outlines sit on the rooms.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
