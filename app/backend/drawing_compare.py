"""
TakeOff.ai — Drawing revision comparison (blue/red diff over grey).
Closes memory/TOGAL_PARITY_REAUDIT.md #8: "Drawing compare absent — fake
Rev A/B/C buttons; Comparison.jsx is a marketing page."

Matches CLAUDE.md §4's services/comparison/ (drawing-diff worker,
Python/OpenCV) in spirit, implemented in-tree with this backend's existing
flat module layout (detection_geometry.py, clip_embeddings.py) rather than
a standalone service, since there's no async job runner to hand it off to
yet — same pragmatic call made throughout this backend.

cv2/numpy are optional here for the same reason every other CV-touching
module in this backend treats them that way (ai/detection_engine.py,
ai/scale_detection.py, clip_embeddings.py): they live in
app/requirements.txt's heavy stack, not backend/requirements.txt, per
CLAUDE.md §2. Both are already listed there (opencv-python-headless,
numpy) for the detection pipeline; this is the first module in this
backend/ tree to use cv2 for alignment/diffing rather than YOLO/OCR
preprocessing, but needs nothing new installed.
"""

import os
import sys
from typing import Optional


def _ensure_ai_on_path():
    ai_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai")
    if ai_dir not in sys.path:
        sys.path.insert(0, ai_dir)


def compare_available() -> bool:
    try:
        import cv2  # noqa: F401
        import numpy  # noqa: F401
        return True
    except ImportError:
        return False


def auto_align(img_a, img_b):
    """
    ORB feature matching + RANSAC homography, aligning img_b onto img_a's
    coordinate frame. Returns (aligned_b, homography, inlier_count) —
    homography is None and inlier_count is the raw good-match count when
    alignment fails, so a caller can decide whether to fall back to
    manual_align() instead of silently returning a bad diff.
    """
    import cv2
    import numpy as np

    gray_a = cv2.cvtColor(img_a, cv2.COLOR_BGR2GRAY)
    gray_b = cv2.cvtColor(img_b, cv2.COLOR_BGR2GRAY)

    orb = cv2.ORB_create(nfeatures=3000)
    kp_a, des_a = orb.detectAndCompute(gray_a, None)
    kp_b, des_b = orb.detectAndCompute(gray_b, None)

    if des_a is None or des_b is None:
        return img_b, None, 0

    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    raw_matches = matcher.knnMatch(des_a, des_b, k=2)
    good = [m for m, n in raw_matches if m.distance < 0.75 * n.distance]

    if len(good) < 10:
        return img_b, None, len(good)

    src_pts = np.float32([kp_a[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst_pts = np.float32([kp_b[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)

    homography, mask = cv2.findHomography(dst_pts, src_pts, cv2.RANSAC, 5.0)
    if homography is None:
        return img_b, None, len(good)

    h, w = img_a.shape[:2]
    aligned_b = cv2.warpPerspective(img_b, homography, (w, h))
    inliers = int(mask.sum()) if mask is not None else len(good)
    return aligned_b, homography, inliers


def manual_align(img_a, img_b, points_a, points_b):
    """
    Align using >=4 user-supplied corresponding point pairs, each in its
    own drawing's plan-space pixel coordinates (same convention
    DrawingRenderer.jsx already resolves clicks to for scale calibration —
    see routes/scale_routes.py). Raises ValueError on bad input instead of
    silently producing a garbage diff.
    """
    import cv2
    import numpy as np

    if len(points_a) < 4 or len(points_a) != len(points_b):
        raise ValueError("Manual alignment needs at least 4 matching point pairs")

    src_pts = np.float32(points_b).reshape(-1, 1, 2)
    dst_pts = np.float32(points_a).reshape(-1, 1, 2)
    homography, _ = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)
    if homography is None:
        raise ValueError("Could not compute alignment from the given points")

    h, w = img_a.shape[:2]
    aligned_b = cv2.warpPerspective(img_b, homography, (w, h))
    return aligned_b, homography


def compute_diff(img_a, aligned_b, ink_threshold: int = 200, diff_threshold: int = 30):
    """
    Blue/red-over-grey diff: light grey base (from sheet A), red where ink
    is present in A but not in aligned B (removed), blue where ink is
    present in B but not in A (added). Returns
    (diff_image_bgr, removed_mask, added_mask) — the two masks are what
    quantify_changes() measures.
    """
    import cv2
    import numpy as np

    gray_a = cv2.cvtColor(img_a, cv2.COLOR_BGR2GRAY)
    gray_b = cv2.cvtColor(aligned_b, cv2.COLOR_BGR2GRAY)

    diff = cv2.absdiff(gray_a, gray_b)
    _, changed = cv2.threshold(diff, diff_threshold, 255, cv2.THRESH_BINARY)
    changed = changed > 0

    ink_a = gray_a < ink_threshold
    ink_b = gray_b < ink_threshold

    removed_mask = ink_a & ~ink_b & changed
    added_mask = ink_b & ~ink_a & changed

    base = cv2.cvtColor(gray_a, cv2.COLOR_GRAY2BGR)
    grey_wash = cv2.addWeighted(base, 0.35, np.full_like(base, 255), 0.65, 0)

    result = grey_wash.copy()
    result[removed_mask] = (60, 60, 220)   # BGR red — removed
    result[added_mask] = (220, 110, 60)    # BGR blue — added

    return result, removed_mask, added_mask


def quantify_changes(removed_mask, added_mask, scale_ratio: Optional[float] = None, dpi: int = 300) -> dict:
    """
    One-click change quantification: pixel counts and distinct-region
    counts always; real-world sqft only if the sheet has a calibrated
    scale (routes/scale_routes.py) — never fabricate a conversion without one.
    """
    import cv2

    removed_px = int(removed_mask.sum())
    added_px = int(added_mask.sum())

    num_removed, _ = cv2.connectedComponents(removed_mask.astype("uint8"))
    num_added, _ = cv2.connectedComponents(added_mask.astype("uint8"))

    result = {
        "removed_px": removed_px,
        "added_px": added_px,
        "removed_regions": max(num_removed - 1, 0),  # component 0 is background
        "added_regions": max(num_added - 1, 0),
    }

    if scale_ratio:
        _ensure_ai_on_path()
        from preprocessing import pixels_to_sqft
        result["removed_sqft"] = round(pixels_to_sqft(removed_px, scale_ratio, dpi), 1)
        result["added_sqft"] = round(pixels_to_sqft(added_px, scale_ratio, dpi), 1)

    return result
