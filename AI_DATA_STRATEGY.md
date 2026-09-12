# AI_DATA_STRATEGY.md — TakeOff.ai Training & Feedback Data Plan

**Audit date:** 2026-08-07  
**Context:** Repository has training/eval/registry **code** (`app/backend/ml/*`, `app/backend/training/`, `app/training/train.py`) but **zero trained weights** and no committed labeled dataset. Vector-PDF AUTODETECT does not need ML data; raster AI takeoff does.

---

## 1. What data you need NOW

### Immediately (unblock MVP demo)

| Data | Purpose | Format | Notes |
|------|---------|--------|-------|
| 20–50 **vector** architectural PDFs | Demo AUTODETECT without ML | PDF | Already works via `geometry/vector_pdf.py` |
| 30–50 **raster/scanned** floor plans with ground-truth room polygons | Prove YOLO/SAM path | PNG/PDF + COCO/YOLO labels | Required before claiming AI takeoff |
| Per-sheet **scale ground truth** | Measurement accuracy | `scale_ratio` + known dimension | Without this, mIoU ≠ quantity accuracy |
| Title-block crops (50+) | OCR auto-naming eval | Image + JSON fields | Feeds `title_block_ocr.py` fixtures |

### Near-term (credible AI MVP)

| Class | Label type | Why |
|-------|------------|-----|
| Rooms / spaces | Instance polygons + room type | Core Togal-button areas |
| Walls | Polylines or thin polygons | Linear LF |
| Doors | Instance bbox/polygon | Counts |
| Windows | Instance bbox/polygon | Counts |
| Stairs, storage, balcony | Instance | Class map already in `InferenceEngine.CLASSES` |
| Plumbing fixtures / appliances (optional v1) | Bbox | Togal counts these; defer if needed |
| Scale bars / text | Weak labels or OCR fixtures | Scale detection |

`CLASSES` in `ai/inference/engine.py`: living, bedroom, bathroom, kitchen, wall, door, window, balcony, front_door, stair, storage.

---

## 2. What you can obtain from public datasets

| Source | Useful for | Limits | Repo hooks |
|--------|------------|--------|------------|
| **CubiCasa5K** | Room segmentation / floor-plan layout | Residential; not US construction docs; licensing check | `ml/datasets/acquire_cubicasa.py` + tests |
| Other public floor-plan CV sets (e.g. R2V, publicly released FP datasets) | Bootstrap rooms | Domain gap to AEC CD sets | `ml/datasets/bootstrap_public.py` |
| Synthetic floor plans | Pretrain | Won’t match scanned permit sets | Augmentation via albumentations (deps listed) |

**Public data is enough to:** bootstrap a room-seg model, validate the training pipeline (`train_yolov8_seg.py`), and exercise `ml/eval`.

**Public data is NOT enough to:** claim Togal-competitive accuracy on real estimator plan sets (disciplines, RCP, MEP symbols, messy scans).

---

## 3. What must be manually annotated

| Must annotate | Why public data fails |
|---------------|----------------------|
| Real **construction document** sheets (A-series floor plans, RCP) | Lineweight, stamps, grids, Xrefs, scan noise |
| Doors/windows/fixtures **as drawn in your target market** | Symbol libraries differ by region/firm |
| Walls as **takeoff-relevant centerlines** | CubiCasa walls ≠ estimator wall LF |
| Multi-scale sheets, details, enlarged plans | Models overfit to single residential style |
| CorrectionEvent-derived hard examples | Production distribution shift |

Use Label Studio export path already sketched in `ml/annotation/label_studio.py` / `formats.py`.

---

## 4. What objects should be labeled (priority order)

### P0 — MVP detector

1. **Space / room** polygons (type optional at first; “space” vs typed rooms)  
2. **Door** instances  
3. **Window** instances  
4. **Wall** (if not derived from room adjacency — prefer explicit if targeting wall LF quality)

### P1 — Match Togal button counts

5. Plumbing fixtures (toilet, sink, tub, shower)  
6. Appliances (if architectural)  
7. Stairs / elevators  
8. Columns (if structural takeoff later)

### P2 — Search & organize

9. Title block fields (sheet no, title, discipline, revision)  
10. Common detail callouts / grid bubbles (for search, not takeoff)

### Do NOT label yet

- Full MEP symbology libraries  
- Spec book clauses  
- Structural rebar  
- Civil/site grading  

---

## 5. How many examples for MVP

| Task | Minimum to train something demable | Serious MVP gate | Notes |
|------|------------------------------------|------------------|-------|
| Room segmentation | **300–500** sheets (or CubiCasa pretrain + **100** in-domain fine-tune) | **1,000–2,000** in-domain sheets | Augment heavily; tile large sheets |
| Doors/windows detection | **1,000–3,000** instances (~150–400 sheets) | **10k+** instances | Class imbalance careful |
| Scale OCR eval | **100** sheets with known scale | **500** | Not necessarily for training |
| Golden eval holdout | **50** sheets never trained on | **200+** | Used by `ml/eval` promotion |

**Rule:** Prefer CubiCasa (or similar) **pretrain → fine-tune on 100–300 real AEC sheets** over training from scratch on tiny data.

---

## 6. When fine-tuning becomes worthwhile

| Situation | Recommendation |
|-----------|----------------|
| Vector PDFs only in ICP | **Don’t fine-tune** — ship `vector_pdf` AUTODETECT |
| Need scanned/raster plans | Fine-tune **after** ≥100 in-domain labeled sheets + frozen eval set |
| Zero-shot SAM2 for interactive rooms | Use **pre-trained SAM2** for assisted labeling / click-to-segment **before** investing in YOLO fine-tune |
| Door/fixture counts fail heuristics | Fine-tune symbol YOLO when vector_symbol_match error rate > estimator tolerance |
| CorrectionEvent volume | Fine-tune / retrain when you have **≥500 accepted corrections** or clear systematic errors |

**Do not** fine-tune because the roadmap says so. Fine-tune when eval metrics on *your* golden set plateau with zero-shot/pretrained approaches.

---

## 7. User feedback → training data

Already modeled in DB: `CorrectionEvent` (`action`: accept | reject | relabel | edit; `before`/`after`; `model_version`; `user_id`).

| User action | Training use |
|-------------|--------------|
| **Accept** | Positive example; hard-negative mining low priority |
| **Reject** | Hard negative / remove from positive set |
| **Relabel** | Class correction |
| **Edit geometry** | Improved polygon/polyline GT (highest value) |
| Manual draws (once Phase 2 ships) | Pure GT (`source=manual`) |
| Search clicks / count confirms | Weak labels for retrieval / detectors |
| Scale calibrate / accept OCR | Scale supervision |

Pipeline already sketched: `ml/training/export_corrections.py` → dataset versioning (`ml/datasets/versioning.py`) → `retrain.py` → `ModelVersion` → `ml/eval/promote.py`.

**Operational rule:** Only export corrections from sheets with **confirmed scale** and **org consent** (ToS).

---

## 8. Pretrained vs fine-tune vs custom vs deterministic vs LLM

| Capability | Strategy |
|------------|----------|
| Vector PDF room/wall measure | **DETERMINISTIC** (`vector_pdf`) — already correct approach |
| Interactive room cutout for labeling | **PRE-TRAINED** SAM2 |
| Production room seg on scans | **FINE-TUNING RECOMMENDED** (YOLO-seg / Mask R-CNN) on in-domain data |
| Doors/windows/fixtures | **FINE-TUNING RECOMMENDED**; geometric match only as bootstrap |
| Scale from text | **DETERMINISTIC** OCR patterns + manual calibrate; LLM not needed |
| Title block fields | OCR **DETERMINISTIC** / small rules; LLM/VLM optional later |
| Image search | **PRE-TRAINED** CLIP embeddings |
| Chat over quantities | **LLM** with grounded JSON context |
| Spec Q&A | **LLM + RAG** later; not MVP |
| Wall LF from raster | Prefer **DETERMINISTIC** from room polygons or classical CV; custom wall CNN only if eval demands |
| MEP from area formulas | **DELETE** from measured output — not a model problem |

---

## 9. Dataset versioning & governance

Use existing hooks:

- `ml/datasets/versioning.py` — dataset versions  
- `ModelVersion` table — stage + metrics  
- `ml/eval/harness.py` / `promote.py` — gates  
- DVC mentioned in CLAUDE.md — **not present** in this repo; either add DVC or store manifests in object storage

**Promotion gate (recommended):**  
Do not set `ACTIVE` unless golden-set measurement error (area/LF/count) is within agreed band (e.g. ≤5–10% vs estimator GT on residential floor plans) **and** mIoU/mAP thresholds pass.

---

## 10. MVP data checklist (practical)

- [ ] 40 vector PDFs for sales demos (no ML)  
- [ ] CubiCasa (or equivalent) acquired + one training run producing `best.pt`  
- [ ] 100 in-domain sheets labeled (rooms + doors + windows)  
- [ ] 50-sheet golden holdout with scale GT  
- [ ] Weights installed at `models/best.pt` per `models/README.md`  
- [ ] `python -m ml.preflight` green in GPU environment  
- [ ] CorrectionEvent UI working on real sheets (Phase 2) before collecting prod flywheel  

**Until the checklist is done, marketing claims of AI accuracy are unsupported by this repository.**
