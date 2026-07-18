"""
Dataset versioning (mission item #3).

Training is only reproducible if you can say *exactly which data* produced a set
of weights. This module content-addresses a dataset: it hashes every file, builds
a canonical manifest, and derives an immutable version id from that manifest
(sha256 of the canonical JSON). Two snapshots of identical bytes get the same id;
any added/removed/edited label or image changes it. A ``DatasetVersion`` records
the id, lineage (parent version), class list, split counts, and timestamp.

Pairs with ``models.ModelVersion`` (which can store the ``dataset_version`` id)
so every promoted model points back at the exact, verifiable data it trained on.

Pure stdlib (hashlib/json/os) — no heavy deps — so the whole thing runs in CI.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Optional


def bytes_digest(data: bytes) -> str:
    """sha256 hex of raw bytes."""
    return hashlib.sha256(data).hexdigest()


def file_digest(path: os.PathLike | str, *, chunk: int = 1 << 20) -> str:
    """Streaming sha256 hex of a file (chunked so large rasters don't load fully)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def build_manifest(entries: Iterable[tuple[str, str, int]]) -> dict:
    """Canonical manifest from (relpath, sha256, size) triples.

    Sorted by path so the manifest — and therefore the version id — is
    deterministic regardless of filesystem walk order.
    """
    files = sorted(
        ({"path": p.replace(os.sep, "/"), "sha256": d, "size": int(s)} for p, d, s in entries),
        key=lambda e: e["path"],
    )
    total = sum(e["size"] for e in files)
    return {"files": files, "file_count": len(files), "total_bytes": total}


def manifest_id(manifest: dict) -> str:
    """Immutable version id = sha256 of the manifest's canonical JSON (short 16-hex)."""
    canonical = json.dumps(manifest["files"], sort_keys=True, separators=(",", ":"))
    return bytes_digest(canonical.encode())[:16]


def diff_manifests(old: dict, new: dict) -> dict:
    """What changed between two manifests: added / removed / changed paths."""
    old_map = {e["path"]: e["sha256"] for e in old.get("files", [])}
    new_map = {e["path"]: e["sha256"] for e in new.get("files", [])}
    added = sorted(new_map.keys() - old_map.keys())
    removed = sorted(old_map.keys() - new_map.keys())
    changed = sorted(p for p in old_map.keys() & new_map.keys() if old_map[p] != new_map[p])
    return {"added": added, "removed": removed, "changed": changed}


@dataclass
class DatasetVersion:
    """An immutable, content-addressed snapshot of a training dataset."""
    id: str
    name: str
    created_at: str                      # ISO8601; passed in (no wall-clock in pure code)
    class_names: list = field(default_factory=list)
    splits: dict = field(default_factory=dict)   # {"train": n, "val": n, ...}
    parent: Optional[str] = None
    manifest: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


def snapshot_dataset(
    root: os.PathLike | str,
    *,
    name: str,
    created_at: str,
    class_names: Optional[list] = None,
    parent: Optional[str] = None,
    include_ext: tuple = (".png", ".jpg", ".jpeg", ".txt", ".yaml", ".json"),
) -> DatasetVersion:
    """Walk ``root`` and produce a content-addressed ``DatasetVersion``.

    ``created_at`` is injected (ISO8601 string) — this module never calls the
    wall clock, so snapshots are reproducible and testable. Split counts are
    derived from ``labels/<split>/`` image-label pairs when present.
    """
    root = Path(root)
    entries: list[tuple[str, str, int]] = []
    for dirpath, _, files in os.walk(root):
        for fn in files:
            if include_ext and not fn.lower().endswith(include_ext):
                continue
            fp = Path(dirpath) / fn
            rel = str(fp.relative_to(root))
            entries.append((rel, file_digest(fp), fp.stat().st_size))

    manifest = build_manifest(entries)
    splits: dict = {}
    for e in manifest["files"]:
        parts = e["path"].split("/")
        if len(parts) >= 2 and parts[0] == "labels" and e["path"].endswith(".txt"):
            splits[parts[1]] = splits.get(parts[1], 0) + 1

    return DatasetVersion(
        id=manifest_id(manifest),
        name=name,
        created_at=created_at,
        class_names=list(class_names or []),
        splits=splits,
        parent=parent,
        manifest=manifest,
    )


def write_version(version: DatasetVersion, path: os.PathLike | str) -> None:
    """Persist a version record as JSON (the queryable index next to the data)."""
    Path(path).write_text(json.dumps(version.as_dict(), indent=2, sort_keys=True))


def load_version(path: os.PathLike | str) -> DatasetVersion:
    """Load a version record written by ``write_version``."""
    return DatasetVersion(**json.loads(Path(path).read_text()))
