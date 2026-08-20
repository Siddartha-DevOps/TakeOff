# program.md — TakeOff.ai ML Research Harness

The standing spec for disciplined, non-gameable model work in this repo. Read
before any training/eval change. Paths here are **real** (verified against the
tree), not placeholders.

---

## 1. The harness

`prepare.py` (repo root) is the **immutable measurement harness**. It scores the
current model against a **frozen, checksum-locked** held-out set and prints one
scalar:

```
val_map=<float in [0,1]>   real segmentation mAP@0.5 on the frozen eval set
val_map=-1                 HARD REJECT (any failure — see §4)
```

- **Scope:** eval-only. It does not train and never writes to the eval set.
- **Metric:** `metrics.seg.map50` (seg mAP@0.5), surfaced by `evaluate_model()`
  in `app/training/train.py` as `mAP50_seg`. Box metrics are still computed and
  returned, just not used as `val_map`.
- **Gate:** `val_map ≥ 0.50` passes; below that → revert (§2). **No fixed
  "target" yet** — it is intentionally left uncalibrated until several real
  `experiment_log.md` runs exist to calibrate against. Do not invent a target.
- **Not the product metric:** CLAUDE.md's "≥95% space-detection accuracy" is a
  separate, **product-level** measure (detection rate the product is judged on),
  **not** this harness's seg mAP@0.5 gate. They are different metrics on
  different scales — do not conflate them.
- **Model under test:** `app/backend/models/best.pt` (the promoted inference
  path `server.py` loads), overridable via `--weights` or `$MODEL_PATH`.

### Real paths

| Thing | Path |
|---|---|
| Harness | `prepare.py` |
| Eval scorer | `app/training/train.py` → `evaluate_model()` |
| Training entrypoints | `app/backend/ml/training/run_training.py`, `app/training/train.py` |
| Model under test | `app/backend/models/best.pt` (or `$MODEL_PATH`) |
| Frozen eval set | `data/eval_set/{images,labels}/`, `data/eval_set/data.yaml` |
| Eval checksum lock | `data/eval_set/MANIFEST.sha256` |
| Experiment log | `experiment_log.md` |

---

## 2. Rules (do not violate)

- You **may** edit `app/training/train.py` and `app/backend/ml/**` freely.
- You **may NOT** edit `prepare.py`, anything under `data/eval_set/`, or
  `MANIFEST.sha256` — under any circumstances, even if it would "help".
- After any change to the training code, run `python prepare.py` and record the
  `val_map` it prints.
- `val_map == -1` or an error is a **hard reject**: `git revert` the change and
  try a different approach. **Never** edit the eval set/manifest to make a
  failing run pass — the manifest check will catch it and reject anyway.
- **Log every attempt** to `experiment_log.md`: the change, the hypothesis, and
  the resulting `val_map`.

---

## 3. Establishing the frozen eval set (one time, by a human)

The eval set does **not** exist yet, so `prepare.py` currently returns
`val_map=-1` ("no frozen eval set"). That is correct, not a bug. To establish it:

1. Put held-out images in `data/eval_set/images/` and YOLO-seg labels in
   `data/eval_set/labels/` (every image must have ≥1 ground-truth object).
2. Write `data/eval_set/data.yaml` (val → this set, matching class list).
3. Run `python prepare.py --freeze` once to write `MANIFEST.sha256`.
4. Commit the eval set + manifest. From then on it is immutable.

**Source constraint:** the eval set must be **commercially clean** — proprietary
held-out plans only. Do **not** use CubiCasa5K / RPLAN / Structured3D (see §5).

---

## 4. `val_map = -1` failure table

| Condition | Why it rejects |
|---|---|
| No `data/eval_set/data.yaml` | nothing to measure against |
| Eval set ≠ `MANIFEST.sha256` | frozen set was modified — not allowed |
| No weights at the model path | nothing to score |
| No eval image has ground truth | eval set is degenerate |
| **Zero predictions on GT-bearing images** | model is **broken**, not merely weak |
| `evaluate_model` raises / no `mAP50_seg` / non-finite | eval could not produce a real number |

The zero-prediction guard is the point: a model that emits nothing scores mAP=0
through the normal path and looks like "a bad model." Here it is a distinct
**hard reject**, so a wiring bug can never be mistaken for a low-but-real score.

---

## 5. Data licensing constraints (binding)

- **CubiCasa5K — CC BY-NC 4.0 (NonCommercial).** Not for the commercial model.
  The earlier mAP 0.02–0.06 model was trained on CubiCasa and is **tainted**: do
  not use, publish, or reference it as a commercial asset.
- **RPLAN, Structured3D — research/non-commercial Terms of Use**, and both
  forbid redistribution. Not for the commercial model, not re-hostable.
- **ResPlan — CC BY 4.0 (commercial-safe).** Optional *pretraining* only; it is
  vector-only and would need rendering to images. On the shelf for now.
- **Commercial training data = the owner's 5,000 proprietary CAD floor plans**
  (vector + polygon room masks) — the Route B dataset below.

---

## 6. Current task list (real, in order)

- **P0 — Frozen eval set.** Build + `--freeze` `data/eval_set/` from proprietary
  held-out plans. Until this exists, `prepare.py` returns -1 and nothing below
  can be measured. *(Blocks everything.)*
- **P1 — Route B dataset pipeline.** Convert the 5,000 proprietary CAD plans
  (vector + polygon masks) to YOLOv8-seg: CAD→PNG render, polygon→normalized
  labels (reuse `bootstrap_public.build_label_lines`), room-type→space-class
  remap. Commercially clean.
- **P2 — Train + measure.** Train the spaces model on the clean set via
  `run_training.py`, promote `best.pt`, run `python prepare.py`, log `val_map`.
  Pass gate = `val_map` (seg mAP@0.5) ≥ 0.50. No target set yet — calibrate one
  from real `experiment_log.md` entries; do not invent it.
- **P3 — train-then-eval mode.** Extend the loop so `prepare.py` (or a sibling)
  can drive training with the edited code, then score — once eval-only is proven.
- **P4 — Symbols model.** Doors/windows/MEP detection, once spaces clears the gate.

---

## 7. Status of this change

- Added `prepare.py` (eval-only harness) and extended `evaluate_model()` to
  surface `mAP50_seg` alongside the existing box metrics.
- `data/eval_set/` intentionally **not** created here — it must be populated
  with real proprietary data by a human, then frozen. `prepare.py` correctly
  returns `val_map=-1` until then.
