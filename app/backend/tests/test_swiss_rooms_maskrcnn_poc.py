import gzip
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

from ml.datasets import adapt_swiss_rooms_maskrcnn_poc as adapter


TRANSFORM = {"image_size_px": [101, 101], "source_bounds_m": [0, 0, 8, 8],
             "padding_m": 1, "pixels_per_metre": 10}


def test_rle_round_trip_preserves_interior_hole():
    mask, rings = adapter.rasterize_room(
        "POLYGON ((1 1, 7 1, 7 7, 1 7, 1 1), (3 3, 5 3, 5 5, 3 5, 3 3))",
        TRANSFORM,
    )
    decoded = adapter.decode_uncompressed_rle(adapter.encode_uncompressed_rle(mask))
    assert rings == 1
    assert np.array_equal(mask, decoded)
    assert decoded[50, 50] == 0
    assert decoded[30, 30] == 1


def test_rle_round_trip_when_first_fortran_pixel_is_positive():
    mask = np.ones((3, 4), dtype=np.uint8)
    mask[1, 2] = 0
    rle = adapter.encode_uncompressed_rle(mask)
    assert rle["counts"][0] == 0
    assert np.array_equal(adapter.decode_uncompressed_rle(rle), mask)


def test_multiple_instances_remain_independent():
    left, _ = adapter.rasterize_room("POLYGON ((1 1, 3 1, 3 3, 1 3, 1 1))", TRANSFORM)
    right, _ = adapter.rasterize_room("POLYGON ((4 4, 7 4, 7 7, 4 7, 4 4))", TRANSFORM)
    assert left.sum() > 0 and right.sum() > 0
    assert not np.array_equal(left, right)


def test_empty_or_invalid_room_is_rejected():
    for wkt in ("POLYGON EMPTY", "POLYGON ((1 1, 1 1, 1 1, 1 1))"):
        try:
            adapter.rasterize_room(wkt, TRANSFORM)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid room was accepted")


def test_selection_is_deterministic_and_split_preserving():
    rows=[]; audit=[]
    for split, count in adapter.POC_SPLIT_QUOTAS.items():
        for index in range(count + 5):
            key=f"{split}-{index}"
            rows.append({"floor_key":key,"floor_id":key,"split":split,"building_key":f"{split}-b-{index}"})
            audit.append({"floor_key":key,"authoritative_instance_count":index % 10,
                          "rejected_instance_count":1 if index % 4 == 0 else 0})
    source={"eligible_floors":rows}
    audit_manifest={"floors":audit,"rejected_instances":[]}
    first,_=adapter.select_poc_floors(source["eligible_floors"],audit_manifest)
    second,_=adapter.select_poc_floors(source["eligible_floors"],audit_manifest)
    assert [r["floor_key"] for r in first] == [r["floor_key"] for r in second]
    assert dict(__import__('collections').Counter(r['split'] for r in first)) == adapter.POC_SPLIT_QUOTAS
