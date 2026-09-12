"""
ML readiness preflight — the "can we train / serve a real model today?" doctor.

Answers, from the actual environment, the two questions the audit raised:
  - can this box **train** a YOLO model?  (deps + a dataset present)
  - can this box **serve** real inference? (deps + weights present)

It probes dependency importability (without importing the heavy libs — uses
``importlib.util.find_spec`` so a missing torch doesn't blow up the check),
inspects the weights contract (``models/best.pt``), and validates a dataset
(``data.yaml`` + label files). The aggregation logic is pure and unit-tested;
the CLI (`python -m ml.preflight`) prints an actionable report and exits non-zero
when not ready — usable as a CI/deploy gate.

No heavy deps: this module is stdlib-only so it runs anywhere, including the
CPU-light CI box.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional

# Import names (not pip names): cv2 = opencv, PIL = pillow.
TRAIN_DEPS = ["torch", "ultralytics", "cv2", "numpy", "PIL"]
SERVE_DEPS = ["torch", "ultralytics", "cv2", "numpy"]
OPTIONAL_DEPS = ["pytesseract", "sam2", "dvc", "onnxruntime"]

BACKEND_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WEIGHTS = BACKEND_ROOT / "models" / "best.pt"


# --------------------------------------------------------------------------- #
# Probes (do I/O) — thin, so the aggregation stays pure/testable.
# --------------------------------------------------------------------------- #
SpecFinder = Callable[[str], object]


def dependency_present(name: str, *, find_spec: Optional[SpecFinder] = None) -> bool:
    """True if ``name`` is importable, without actually importing it.

    ``find_spec`` is injectable for tests; defaults to importlib. Guarded because
    a broken/namespace package can raise inside find_spec.
    """
    finder = find_spec or importlib.util.find_spec
    try:
        return finder(name) is not None
    except (ImportError, ValueError, ModuleNotFoundError):
        return False


def check_dependencies(names, *, find_spec: Optional[SpecFinder] = None) -> dict:
    """Map each dependency import-name -> present(bool)."""
    return {n: dependency_present(n, find_spec=find_spec) for n in names}


def check_path(path) -> dict:
    """Existence + size (bytes) of a file path."""
    p = Path(path)
    if p.is_file():
        return {"exists": True, "bytes": p.stat().st_size, "path": str(p)}
    return {"exists": False, "bytes": 0, "path": str(p)}


def parse_data_yaml(text: str) -> dict:
    """Minimal, dependency-free parse of an Ultralytics data.yaml.

    Extracts ``nc`` and the ``names:`` list without requiring PyYAML (keeps the
    doctor stdlib-only). Tolerant of both ``names: [a, b]`` and the indented
    ``  0: a`` block form written by the training/bootstrap scripts.
    """
    nc = None
    names: list[str] = []
    in_names_block = False
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if stripped.startswith("nc:"):
            try:
                nc = int(stripped.split(":", 1)[1].strip())
            except ValueError:
                pass
            in_names_block = False
        elif stripped.startswith("names:"):
            rest = stripped.split(":", 1)[1].strip()
            if rest.startswith("[") and rest.endswith("]"):
                names = [n.strip().strip("'\"") for n in rest[1:-1].split(",") if n.strip()]
                in_names_block = False
            else:
                in_names_block = True
        elif in_names_block and (line.startswith(" ") or line.startswith("\t")) and ":" in stripped:
            names.append(stripped.split(":", 1)[1].strip().strip("'\""))
        elif in_names_block and stripped and not line.startswith((" ", "\t")):
            in_names_block = False
    return {"nc": nc, "names": names}


def check_dataset(data_yaml) -> dict:
    """Validate a dataset: data.yaml present, parseable, with at least one label file."""
    p = Path(data_yaml)
    if not p.is_file():
        return {"exists": False, "nc": None, "n_classes": 0, "n_label_files": 0, "path": str(p)}
    meta = parse_data_yaml(p.read_text())
    root = p.parent
    n_labels = sum(1 for _ in (root / "labels").rglob("*.txt")) if (root / "labels").is_dir() else 0
    return {
        "exists": True,
        "nc": meta["nc"],
        "n_classes": len(meta["names"]),
        "n_label_files": n_labels,
        "path": str(p),
    }


# --------------------------------------------------------------------------- #
# Pure aggregation — unit-tested with injected statuses.
# --------------------------------------------------------------------------- #
@dataclass
class Readiness:
    can_train: bool
    can_serve: bool
    dependencies: dict = field(default_factory=dict)
    optional: dict = field(default_factory=dict)
    weights: dict = field(default_factory=dict)
    dataset: dict = field(default_factory=dict)
    blockers: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def build_readiness(deps: dict, optional: dict, weights: dict, dataset: dict) -> Readiness:
    """Combine probe results into can_train / can_serve verdicts + blockers.

    - **serve** needs all SERVE_DEPS importable AND weights present.
    - **train** needs all TRAIN_DEPS importable AND a dataset with ≥1 label file.
    """
    blockers: list[str] = []

    missing_serve = [d for d in SERVE_DEPS if not deps.get(d)]
    missing_train = [d for d in TRAIN_DEPS if not deps.get(d)]
    for d in sorted(set(missing_serve) | set(missing_train)):
        blockers.append(f"missing dependency: {d} (pip install -r requirements-ml.txt)")

    if not weights.get("exists"):
        blockers.append(f"no trained weights at {weights.get('path', 'models/best.pt')}")

    if not dataset.get("exists"):
        blockers.append("no dataset (data.yaml) — run Phase 2 dataset build")
    elif dataset.get("n_label_files", 0) == 0:
        blockers.append("dataset has no label files (labels/**/*.txt)")

    can_serve = not missing_serve and bool(weights.get("exists"))
    can_train = not missing_train and bool(dataset.get("exists")) and dataset.get("n_label_files", 0) > 0

    return Readiness(
        can_train=can_train, can_serve=can_serve,
        dependencies=deps, optional=optional, weights=weights, dataset=dataset,
        blockers=blockers,
    )


def run_preflight(*, weights_path=DEFAULT_WEIGHTS, data_yaml: Optional[str] = None,
                  find_spec: Optional[SpecFinder] = None) -> Readiness:
    """Run every probe against the real environment and aggregate."""
    deps = check_dependencies(sorted(set(TRAIN_DEPS) | set(SERVE_DEPS)), find_spec=find_spec)
    optional = check_dependencies(OPTIONAL_DEPS, find_spec=find_spec)
    weights = check_path(weights_path)
    dataset = check_dataset(data_yaml) if data_yaml else {
        "exists": False, "nc": None, "n_classes": 0, "n_label_files": 0, "path": None,
    }
    return build_readiness(deps, optional, weights, dataset)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _format_report(r: Readiness) -> str:
    ok = lambda b: "✅" if b else "❌"
    lines = ["TakeOff.ai — ML readiness preflight", "=" * 38]
    lines.append(f"can_train: {ok(r.can_train)}   can_serve: {ok(r.can_serve)}")
    lines.append("\nrequired dependencies:")
    for name, present in r.dependencies.items():
        lines.append(f"  {ok(present)} {name}")
    lines.append("optional dependencies:")
    for name, present in r.optional.items():
        lines.append(f"  {ok(present)} {name}")
    lines.append(f"\nweights: {ok(r.weights.get('exists'))} {r.weights.get('path')}")
    ds = r.dataset
    lines.append(f"dataset: {ok(ds.get('exists'))} {ds.get('path')} "
                 f"(nc={ds.get('nc')}, label_files={ds.get('n_label_files')})")
    if r.blockers:
        lines.append("\nblockers:")
        lines.extend(f"  - {b}" for b in r.blockers)
    else:
        lines.append("\nno blockers — ready.")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="TakeOff.ai ML readiness preflight")
    ap.add_argument("--weights", default=str(DEFAULT_WEIGHTS), help="path to trained weights")
    ap.add_argument("--data", default=None, help="path to dataset data.yaml")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of a report")
    ap.add_argument("--require", choices=["train", "serve"], default=None,
                    help="exit non-zero unless this capability is ready")
    args = ap.parse_args(argv)

    r = run_preflight(weights_path=args.weights, data_yaml=args.data)
    print(json.dumps(r.as_dict(), indent=2) if args.json else _format_report(r))

    if args.require == "train":
        return 0 if r.can_train else 1
    if args.require == "serve":
        return 0 if r.can_serve else 1
    return 0  # report-only mode never fails the shell


if __name__ == "__main__":
    sys.exit(main())
