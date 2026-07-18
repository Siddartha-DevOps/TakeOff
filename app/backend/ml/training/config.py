"""
Training configuration (Phase 3).

A validated, serializable hyperparameter set for a YOLOv8-seg run, plus the
mapping from a training *task* to the weights path the inference stack loads.
Defaults are tuned for construction drawings (imgsz 1280 — large sheets — and a
segmentation base). Pure/stdlib and unit-tested; ultralytics is never imported
here (it's the runner's job).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

BACKEND_ROOT = Path(__file__).resolve().parents[2]

# task -> the stable weights path the inference stack loads (see models/README.md)
TASK_WEIGHTS = {
    "spaces": BACKEND_ROOT / "models" / "best.pt",
    "symbols": BACKEND_ROOT / "ai" / "models" / "symbol_counts" / "yolov8-seg.pt",
}


@dataclass
class TrainConfig:
    """Hyperparameters for one YOLOv8-seg training run."""
    task: str = "spaces"                    # 'spaces' | 'symbols'
    base_model: str = "yolov8m-seg.pt"      # base weights to fine-tune
    epochs: int = 100
    imgsz: int = 1280                       # large construction sheets
    batch: int = 16                         # -1 = ultralytics auto-batch
    patience: int = 20                      # early-stop patience (epochs)
    device: str = "auto"                    # 'auto' | 'cpu' | 'cuda:0' | 'mps'
    seed: int = 0
    cos_lr: bool = True
    augment: bool = True
    project_name: str = "takeoff"           # ultralytics run name
    output_root: Optional[str] = None       # defaults to <backend>/models/runs

    def validate(self) -> "TrainConfig":
        if self.task not in TASK_WEIGHTS:
            raise ValueError(f"unknown task {self.task!r}; expected one of {sorted(TASK_WEIGHTS)}")
        if self.epochs <= 0:
            raise ValueError("epochs must be > 0")
        if self.imgsz <= 0 or self.imgsz % 32 != 0:
            raise ValueError("imgsz must be a positive multiple of 32 (YOLO requirement)")
        if self.batch == 0:
            raise ValueError("batch must be non-zero (-1 = auto)")
        if self.patience < 0:
            raise ValueError("patience must be >= 0")
        return self

    @classmethod
    def from_dict(cls, data: dict) -> "TrainConfig":
        known = {f: data[f] for f in cls.__dataclass_fields__ if f in data}
        return cls(**known).validate()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def smoke(cls, task: str = "spaces") -> "TrainConfig":
        """A fast 1-epoch config to verify the pipeline end-to-end (not for accuracy)."""
        return cls(task=task, epochs=1, imgsz=320, batch=2, patience=0,
                   project_name="smoke", augment=False).validate()

    def weights_target(self) -> Path:
        """Where the promoted best.pt is copied for the inference stack to load."""
        return TASK_WEIGHTS[self.task]

    def runs_dir(self) -> Path:
        root = Path(self.output_root) if self.output_root else (BACKEND_ROOT / "models" / "runs")
        return root

    def train_kwargs(self, data_yaml: str | Path, *, device: Optional[str] = None) -> dict:
        """Build the exact kwargs passed to ultralytics ``model.train(**kwargs)``.

        ``device`` overrides the config's (the runner passes a resolved device
        string). Pure — no torch — so the plan is testable.
        """
        return {
            "data": str(data_yaml),
            "task": "segment",
            "epochs": self.epochs,
            "imgsz": self.imgsz,
            "batch": self.batch,
            "patience": self.patience,
            "device": device if device is not None else self.device,
            "seed": self.seed,
            "cos_lr": self.cos_lr,
            "augment": self.augment,
            "project": str(self.runs_dir()),
            "name": f"{self.project_name}_{self.task}",
            "exist_ok": True,
        }
