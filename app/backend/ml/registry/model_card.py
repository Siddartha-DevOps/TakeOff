"""
Model registry cards: a versioned, auditable record of what a model is, what it
scored on the golden set, and whether it passed the promotion gate.

Pairs with the `model_versions` table (models.ModelVersion): the DB row is the
queryable index; the card is the human-readable artifact stored next to the
weights. Pure and testable — no DB.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def build_model_card(
    *,
    name: str,
    version: str,
    task: str,
    eval_report: dict,
    weights_uri: Optional[str] = None,
    dataset_summary: Optional[dict] = None,
    base_model: Optional[str] = None,
) -> dict:
    """Assemble a model-card dict from an eval-harness report + training metadata."""
    metrics = eval_report.get("metrics", {})
    return {
        "name": name,
        "version": version,
        "task": task,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "base_model": base_model,
        "weights_uri": weights_uri,
        "training_data": dataset_summary or {},
        "metrics": {
            "miou": metrics.get("miou"),
            "map@0.5": metrics.get("map"),
            "measurement_error_pct": metrics.get("measurement_error_pct"),
            "golden_samples": metrics.get("n_samples"),
        },
        "gate": {
            "passed": eval_report.get("gate_passed"),
            "reasons": eval_report.get("gate_reasons", []),
            "thresholds": eval_report.get("thresholds", {}),
        },
        "promotable": bool(eval_report.get("gate_passed")),
    }


def card_to_markdown(card: dict) -> str:
    """Render a card as Markdown for the registry / PR description."""
    m = card["metrics"]
    g = card["gate"]
    status = "✅ PASSED" if g["passed"] else "❌ FAILED"
    lines = [
        f"# Model card — {card['name']} `{card['version']}`",
        "",
        f"- **Task:** {card['task']}",
        f"- **Base model:** {card.get('base_model') or '—'}",
        f"- **Weights:** {card.get('weights_uri') or '—'}",
        f"- **Created:** {card['created_at']}",
        "",
        "## Golden-set metrics",
        f"- mIoU (rooms): **{m['miou']}**",
        f"- mAP@0.5 (symbols): **{m['map@0.5']}**",
        f"- Measurement error: **{m['measurement_error_pct']}%**",
        f"- Golden samples: {m['golden_samples']}",
        "",
        f"## Promotion gate: {status}",
    ]
    if g["reasons"]:
        lines += ["", "Failing checks:"] + [f"- {r}" for r in g["reasons"]]
    if card.get("training_data"):
        lines += ["", "## Training data", "```json", json.dumps(card["training_data"], indent=2), "```"]
    return "\n".join(lines) + "\n"


def write_model_card(card: dict, out_dir: str | Path) -> Path:
    """Write card.json + card.md into `out_dir/<name>/<version>/`. Returns the dir."""
    d = Path(out_dir) / card["name"] / card["version"]
    d.mkdir(parents=True, exist_ok=True)
    (d / "card.json").write_text(json.dumps(card, indent=2))
    (d / "card.md").write_text(card_to_markdown(card))
    return d
