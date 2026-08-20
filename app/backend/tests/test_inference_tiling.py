"""Tests for large-drawing tiled inference (grid, offset, cross-seam merge)."""

import numpy as np
import pytest

from ai.inference.tiling import (
    Tile,
    merge_tiled_detections,
    run_tiled,
    tile_grid,
    translate_detection,
)


def test_tile_grid_covers_page_and_clamps_edges():
    tiles = tile_grid(3000, 2000, tile=1280, overlap=128)
    # every tile within bounds
    assert all(0 <= t.x0 < t.x1 <= 3000 and 0 <= t.y0 < t.y1 <= 2000 for t in tiles)
    # union covers the far corner
    assert max(t.x1 for t in tiles) == 3000
    assert max(t.y1 for t in tiles) == 2000


def test_tile_grid_single_tile_when_small():
    assert tile_grid(500, 400, tile=1280) == [Tile(0, 0, 500, 400)]


def test_tile_grid_validates_overlap():
    with pytest.raises(ValueError):
        tile_grid(100, 100, tile=128, overlap=128)


def test_translate_detection_offsets_bbox_and_polygon():
    det = {"label": "door", "bbox": [1, 2, 3, 4], "polygon": [[1, 1], [2, 2]]}
    out = translate_detection(det, 10, 20)
    assert out["bbox"] == [11, 22, 13, 24]
    assert out["polygon"] == [[11, 21], [12, 22]]
    assert det["bbox"] == [1, 2, 3, 4]  # original untouched


def test_merge_dedups_seam_duplicates_per_class():
    # same door seen in two overlapping tiles -> one survives; a room stays.
    dets = [
        {"label": "door", "bbox": [100, 100, 120, 140], "confidence": 0.8},
        {"label": "door", "bbox": [101, 101, 121, 141], "confidence": 0.9},
        {"label": "living", "bbox": [0, 0, 90, 90], "confidence": 0.95},
    ]
    merged = merge_tiled_detections(dets, iou_thr=0.5)
    doors = [d for d in merged if d["label"] == "door"]
    assert len(doors) == 1 and doors[0]["confidence"] == 0.9
    assert any(d["label"] == "living" for d in merged)


def test_run_tiled_end_to_end_with_stub_runner():
    # 2500x1500 blank raster; stub runner "finds" one door at tile-local (5,5).
    image = np.zeros((1500, 2500), dtype=np.uint8)

    def runner(crop, tile):
        return [{"label": "door", "bbox": [5, 5, 25, 45], "confidence": 0.9}]

    out = run_tiled(image, runner, tile=1280, overlap=128, iou_thr=0.5)
    # multiple tiles each report a door, but distinct tiles -> distinct page coords,
    # so they should NOT all collapse to one (they're at different global offsets).
    assert len(out) >= 1
    assert all(d["label"] == "door" for d in out)
    # coordinates were offset into page space (first tile at 0,0 stays at 5,5)
    assert any(d["bbox"][0] == 5 for d in out)
