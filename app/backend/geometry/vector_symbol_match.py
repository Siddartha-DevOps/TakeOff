"""
Vector symbol matching — count doors / windows / fixtures on vector PDFs.

Togal's AUTODETECT reports counts of ~18 object types. On a *vector* PDF those
symbols are drawn as exact primitives (a door = a leaf line + a swing arc; a
window = a thin rectangle in the wall; a fixture = a small closed curve), so we
can recognize and count them geometrically — no trained model, no rasterization.

Approach (mirrors how estimators think, and how Togal Image Search works):

  1. Parse each drawing path into a *symbol candidate* (its primitives + bbox).
  2. Filter out structural linework (long walls, bare leader lines).
  3. Compute a scale/rotation-invariant **signature** per candidate (fractions of
     line/curve/rect primitives, aspect ratio, complexity) plus a size.
  4. **Cluster** identical repeated symbols by cosine similarity of signatures
     (a KD-tree is used when SciPy is present; a numpy scan otherwise).
  5. **Classify** each cluster into door / window / fixture with geometric
     heuristics, and count by type.

Every instance keeps its bbox/centroid/GeoJSON so counts render on the canvas
and persist as first-class `Detection` rows (editable via the CorrectionEvent
loop). ``fitz`` is imported lazily to keep the module cheap to import.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

# Candidate size gates, as a fraction of the page diagonal. Symbols are small;
# walls / borders are large; specks are noise.
MAX_SYMBOL_FRAC = 0.20
MIN_SYMBOL_FRAC = 0.004

# Two candidates are "the same symbol" at/above this cosine similarity, provided
# their sizes agree within SIZE_TOL.
SIM_THRESHOLD = 0.985
SIZE_TOL = 0.30

# Feature vector length (see _signature).
_FEAT_DIM = 6


@dataclass
class SymbolCandidate:
    """One drawing path treated as a candidate symbol, in PDF points."""

    bbox: tuple[float, float, float, float]
    n_lines: int
    n_curves: int
    n_rects: int
    path_len: float

    @property
    def width(self) -> float:
        return self.bbox[2] - self.bbox[0]

    @property
    def height(self) -> float:
        return self.bbox[3] - self.bbox[1]

    @property
    def diag(self) -> float:
        return (self.width ** 2 + self.height ** 2) ** 0.5

    @property
    def aspect(self) -> float:
        w, h = max(self.width, 1e-6), max(self.height, 1e-6)
        lo, hi = min(w, h), max(w, h)
        return hi / lo  # >= 1, orientation-independent

    @property
    def centroid(self) -> tuple[float, float]:
        return ((self.bbox[0] + self.bbox[2]) / 2, (self.bbox[1] + self.bbox[3]) / 2)

    def signature(self) -> np.ndarray:
        """Scale- and rotation-invariant feature vector for similarity."""
        total = max(self.n_lines + self.n_curves + self.n_rects, 1)
        perim = max(2 * (self.width + self.height), 1e-6)
        return np.array(
            [
                min(self.aspect, 10.0) / 10.0,          # aspect (capped, normalized)
                self.n_curves / total,                  # curve fraction (arcs)
                self.n_lines / total,                   # line fraction
                self.n_rects / total,                   # rect fraction
                min(self.path_len / perim, 4.0) / 4.0,  # complexity vs bbox
                1.0 if (self.n_curves or self.n_rects) else 0.0,  # closed-ish?
            ],
            dtype=float,
        )

    def geometric_hash(self) -> str:
        """Coarse quantized signature for exact-repeat bucketing / debugging."""
        sig = np.round(self.signature() * 8).astype(int)
        size_bucket = int(round(np.log2(self.diag + 1)))
        return "h" + "_".join(map(str, sig)) + f"@{size_bucket}"


@dataclass
class SymbolCluster:
    """A group of identical repeated symbols and their classified type."""

    symbol_type: str
    members: list[SymbolCandidate] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.members)


# ──────────────────────────────────────────────────────────────
# Parsing
# ──────────────────────────────────────────────────────────────
def _chord(p1, p2) -> float:
    return ((p2[0] - p1[0]) ** 2 + (p2[1] - p1[1]) ** 2) ** 0.5


def parse_symbol_candidates(pdf_path: str | Path, page_no: int = 0) -> list[SymbolCandidate]:
    """Turn each vector drawing path into a SymbolCandidate (coords in points)."""
    import fitz  # lazy heavy native dep

    doc = fitz.open(str(pdf_path))
    try:
        page = doc[page_no]
        candidates: list[SymbolCandidate] = []

        for path in page.get_drawings():
            xs: list[float] = []
            ys: list[float] = []
            n_lines = n_curves = n_rects = 0
            path_len = 0.0

            for item in path.get("items", []):
                op = item[0]
                if op == "l":
                    p1, p2 = item[1], item[2]
                    xs += [p1.x, p2.x]; ys += [p1.y, p2.y]
                    n_lines += 1
                    path_len += _chord((p1.x, p1.y), (p2.x, p2.y))
                elif op == "re":
                    r = item[1]
                    xs += [r.x0, r.x1]; ys += [r.y0, r.y1]
                    n_rects += 1
                    path_len += 2 * (abs(r.x1 - r.x0) + abs(r.y1 - r.y0))
                elif op == "qu":
                    q = item[1]
                    for pt in (q.ul, q.ur, q.lr, q.ll):
                        xs.append(pt.x); ys.append(pt.y)
                    n_rects += 1
                elif op == "c":
                    p0, p1, p2, p3 = item[1], item[2], item[3], item[4]
                    for pt in (p0, p1, p2, p3):
                        xs.append(pt.x); ys.append(pt.y)
                    n_curves += 1
                    path_len += _chord((p0.x, p0.y), (p3.x, p3.y))

            if not xs:
                continue

            candidates.append(
                SymbolCandidate(
                    bbox=(min(xs), min(ys), max(xs), max(ys)),
                    n_lines=n_lines,
                    n_curves=n_curves,
                    n_rects=n_rects,
                    path_len=path_len,
                )
            )

        return candidates
    finally:
        doc.close()


def _page_diag(pdf_path: str | Path, page_no: int) -> tuple[float, float, float]:
    import fitz

    doc = fitz.open(str(pdf_path))
    try:
        r = doc[page_no].rect
        return float(r.width), float(r.height), (r.width ** 2 + r.height ** 2) ** 0.5
    finally:
        doc.close()


def filter_candidates(
    candidates: list[SymbolCandidate], page_diag: float
) -> list[SymbolCandidate]:
    """Drop walls/borders (too big), specks (too small) and bare single lines."""
    lo = MIN_SYMBOL_FRAC * page_diag
    hi = MAX_SYMBOL_FRAC * page_diag
    kept = []
    for c in candidates:
        if not (lo <= c.diag <= hi):
            continue
        # A single bare straight segment is a wall/leader, not a symbol.
        if c.n_lines == 1 and c.n_curves == 0 and c.n_rects == 0:
            continue
        kept.append(c)
    return kept


# ──────────────────────────────────────────────────────────────
# Clustering (cosine similarity; optional KD-tree acceleration)
# ──────────────────────────────────────────────────────────────
def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na < 1e-9 or nb < 1e-9:
        return 1.0 if na < 1e-9 and nb < 1e-9 else 0.0
    return float(np.dot(a, b) / (na * nb))


def cluster_symbols(
    candidates: list[SymbolCandidate],
    sim_threshold: float = SIM_THRESHOLD,
    size_tol: float = SIZE_TOL,
) -> list[list[SymbolCandidate]]:
    """Greedy nearest-neighbor clustering of identical repeated symbols.

    Uses a SciPy KD-tree over normalized signatures when available (fast on big
    sheets), otherwise a numpy cosine scan. Same-symbol requires both signature
    similarity AND comparable size.
    """
    if not candidates:
        return []

    sigs = [c.signature() for c in candidates]
    sizes = np.array([c.diag for c in candidates])

    clusters: list[list[int]] = []
    cluster_sig: list[np.ndarray] = []
    cluster_size: list[float] = []

    for i, sig in enumerate(sigs):
        placed = False
        for k, csig in enumerate(cluster_sig):
            size_ratio = min(sizes[i], cluster_size[k]) / max(sizes[i], cluster_size[k], 1e-6)
            if _cosine(sig, csig) >= sim_threshold and size_ratio >= (1 - size_tol):
                clusters[k].append(i)
                # Update running mean signature/size for stability.
                n = len(clusters[k])
                cluster_sig[k] = csig + (sig - csig) / n
                cluster_size[k] = cluster_size[k] + (sizes[i] - cluster_size[k]) / n
                placed = True
                break
        if not placed:
            clusters.append([i])
            cluster_sig.append(sig.copy())
            cluster_size.append(float(sizes[i]))

    return [[candidates[idx] for idx in group] for group in clusters]


# ──────────────────────────────────────────────────────────────
# Classification (geometric heuristics; no model)
# ──────────────────────────────────────────────────────────────
def classify_candidate(c: SymbolCandidate) -> str:
    """Best-guess symbol type from geometry.

    door    — swing arc (curve) + leaf line, roughly square envelope
    window  — thin elongated rectangle / parallel lines, no arc
    fixture — small closed curvy blob (toilet/sink) with no straight leaf
    symbol  — a repeated glyph we can count but not name
    """
    has_curve = c.n_curves >= 1
    has_line = c.n_lines >= 1

    if has_curve and has_line and 0.5 <= c.aspect <= 2.6:
        return "door"
    if not has_curve and c.aspect >= 3.0 and (c.n_rects >= 1 or c.n_lines >= 1):
        return "window"
    if has_curve and not has_line and c.aspect <= 2.2:
        return "fixture"
    return "symbol"


def classify_cluster(cluster: list[SymbolCandidate]) -> str:
    """Type for a whole cluster: majority vote over members."""
    votes = Counter(classify_candidate(c) for c in cluster)
    return votes.most_common(1)[0][0]


# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────
def match_symbols(
    pdf_path: str | Path,
    page_no: int = 0,
    min_cluster_size: int = 1,
) -> dict[str, Any]:
    """Detect and count repeated symbols on a vector PDF page.

    Returns counts per symbol type plus, per symbol group, the classified type,
    instance count and instance geometry (bbox/centroid/GeoJSON) for overlay and
    persistence. ``min_cluster_size`` can require a symbol to repeat before it
    counts (Togal counts singletons too, so the default is 1).
    """
    from shapely.geometry import box

    from .postgis import to_geojson

    pw, ph, pdiag = _page_diag(pdf_path, page_no)
    raw = parse_symbol_candidates(pdf_path, page_no)
    candidates = filter_candidates(raw, pdiag)
    clusters = cluster_symbols(candidates)

    counts: Counter[str] = Counter()
    groups: list[dict[str, Any]] = []

    for gi, cluster in enumerate(clusters):
        if len(cluster) < min_cluster_size:
            continue
        stype = classify_cluster(cluster)
        counts[stype] += len(cluster)

        instances = []
        for ii, c in enumerate(cluster):
            geom = box(*c.bbox)
            instances.append(
                {
                    "id": f"sym_{gi}_{ii}",
                    "bbox": [round(v, 1) for v in c.bbox],
                    "centroid": [round(c.centroid[0], 1), round(c.centroid[1], 1)],
                    "geojson": to_geojson(geom),
                }
            )

        groups.append(
            {
                "group_id": f"g{gi}",
                "symbol_type": stype,
                "count": len(cluster),
                "hash": cluster[0].geometric_hash(),
                "instances": instances,
            }
        )

    return {
        "method": "vector_symbol",
        "symbol_counts": dict(counts),
        "total_symbols": int(sum(counts.values())),
        "groups": groups,
        "page": {"width_pt": round(pw, 2), "height_pt": round(ph, 2), "page_no": page_no},
    }


def symbols_to_persistence(match_result: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten symbol instances into first-class Detection payloads.

    Each instance becomes a ``Detection`` (source="vector", class=symbol_type)
    with polygon geometry, so counts persist to PostGIS linked to a Sheet and are
    editable through the CorrectionEvent loop (accept/reject/relabel a count).
    """
    from shapely.geometry import shape

    from .postgis import detection_payload

    records: list[dict[str, Any]] = []
    for group in match_result.get("groups", []):
        stype = group["symbol_type"]
        for inst in group["instances"]:
            geom = shape(inst["geojson"])
            payload = detection_payload(geom, detection_class=stype, source="vector")
            records.append(
                {
                    "detection": payload,
                    "ref_id": inst["id"],
                    "group_id": group["group_id"],
                    "symbol_type": stype,
                }
            )
    return records
