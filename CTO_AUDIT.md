# CTO_AUDIT.md — TakeOff.ai Full Competitive Audit

**Product:** TakeOff / TakeOff.ai  
**Audit date:** 2026-08-07  
**Scope:** Read-only inspection of the live repository. No code was modified for this audit.  
**Companion docs:** `TECH_STACK.md`, `TOGAL_PARITY_MATRIX.md`, `TOGAL_PARITY_ROADMAP.md`, `AI_DATA_STRATEGY.md`

---

## Executive summary

**THIS IS EXACTLY WHERE YOUR PRODUCT IS TODAY.**

TakeOff is a **real FastAPI + React takeoff SaaS shell** with a **working vector-PDF geometry engine**, PostGIS persistence, exports, org/RBAC, Stripe metering hooks, and many Togal-adjacent features scaffolded (search, chat, compare, collab, estimating, eval registry). It is **not** a Turborepo/Next.js/Clerk system as described in `CLAUDE.md`.

The product’s critical path for competing with Togal — **AI detection on real construction drawings + professional manual correction** — is **not shipping**:

1. **Zero trained weights** in `app/backend/models/` (only `.gitkeep` + README). Raster `/analyze` fail-closes with `ModelUnavailableError`.
2. **Manual takeoff tools are missing** on real sheets (`DrawingRenderer` overlays are `pointer-events-none`; annotation store still “Milestone 1”).
3. **Signup is fake** (`Signup.jsx` writes localStorage and never calls `/api/auth/signup`).
4. SAM2 exists but is **unrouted**; CLIP image search is **backend-only**; global ChatWidget is **mock**.

**Credible demo today:** login → create project → upload **vector** PDF → calibrate scale → `/autodetect` → view quantities → export Excel/CSV.

**Not credible today:** “AI takeoff like Togal” on scanned plans; end-to-end estimator HITL; Togal feature parity.

**Stage:** **STAGE 3 — Functional Takeoff MVP** (vector-only, with serious UX holes).  
**Togal parity (core estimator loop):** **~22–28%**.  
**Overall production readiness:** **3.9 / 10**.

---

## Current product stage

### Classification: STAGE 3 — Functional Takeoff MVP

| Stage | Definition | Fit |
|-------|------------|-----|
| 0 Idea | Spec only | No — substantial code |
| 1 UI Prototype | Marketing + fake demos | Surpassed — real APIs |
| 2 Basic MVP | Auth/projects/upload/viewer | Surpassed |
| **3 Functional Takeoff MVP** | **Measure + quantities + export on real drawings** | **YES — via vector AUTODETECT** |
| 4 AI Takeoff MVP | One-click AI on plans, editable | **NO** — no weights; no manual edit on real sheets |
| 5 Production platform | Reliable multi-tenant ops | NO |
| 6 Togal parity | Public feature parity | NO |
| 7 Better than Togal | Clear win on accuracy/workflow | NO |

### Why STAGE 3 (and why not higher)

**Evidence for STAGE 3:**

- Upload: `upload_routes.py` + `FileUploadZone.jsx` + S3/local storage  
- Scale: `scale_routes.py` + two-point calibrate in Takeoff  
- Measure: `geometry/vector_pdf.py` + `quantities.py` → Area / Line / Count  
- Persist: PostGIS `Detection` / `Measurement`; `TakeoffResult`  
- Export: `export_engine.py` Excel/CSV/PDF  

**Evidence against STAGE 4:**

- `models/best.pt` absent; engine raises `ModelUnavailableError`  
- Manual tools promised in UI when AI unavailable **do not exist** on `DrawingRenderer`  
- Accept/reject corrections not usable on real overlays  
- Signup broken — onboarding incomplete  

**Not inflated:** Prior internal docs claiming “~70% Togal shell” describe **breadth of scaffolding**, not **working AI**. This audit scores the **estimator-critical path**, which remains weak.

---

## Current architecture

```
[Browser: Vite React SPA]
        │  Vercel (static)
        │  /api/* rewrite → https://takeoff-api.onrender.com
        ▼
[FastAPI monolith on Render Docker]
        ├─ JWT auth, RBAC, projects, uploads
        ├─ takeoff: /autodetect (vector) + /analyze (YOLO if weights)
        ├─ Celery/Redis OR BackgroundTasks
        ├─ Postgres + PostGIS + pgvector
        ├─ S3/R2 or local disk
        ├─ Stripe, Anthropic, Sentry (env-gated)
        └─ Optional CUDA image (ai/inference/Dockerfile) — not in render.yaml
```

**Divergence from `CLAUDE.md`:** No Next.js, no Clerk, no Inngest/Trigger.dev, no Turborepo packages, no Prisma. SQLAlchemy + Alembic instead.

**Strength:** Separates heavy ML deps (`requirements-ml.txt` / CUDA Dockerfile) from API image — correct instinct.  
**Weakness:** GPU service not actually deployed; Redis not in Render blueprint; frontend/backend stack mismatch with standing spec.

---

## Current AI architecture

| Component | Path | Live? |
|-----------|------|-------|
| InferenceEngine (YOLO-seg) | `ai/inference/engine.py` | Code yes / weights **no** |
| TakeoffAIInference shim | `ai/inference_api.py` | Yes |
| Celery `run_ai_analysis_task` | `celery_app.py` | Yes (needs Redis) |
| BlueprintDetector | `ai/detection_engine.py` | **Unused** by routes |
| SAM2 zero-shot | `ai/sam2_zero_shot.py` | **Unrouted** |
| Symbol YOLO | `ai/detect_symbols.py` | Needs weights; UI unused |
| CLIP + pgvector | `clip_embeddings.py` | Needs torch+CLIP + index |
| Chat | `ai_routes.py` | Needs `ANTHROPIC_API_KEY` |
| Spatial heuristics | `spatial_reasoning.py` | Runs; includes **fake MEP estimates** |
| Vector AUTODETECT | `geometry/vector_pdf.py` | **Primary working “AI” UX** (deterministic) |
| Model registry / eval | `ModelVersion`, `ml/eval/*` | Code ready; no production models |

**Health endpoint** still reports `"mock_mode"` when no model — naming leftover after mock removal (`server.py`).

---

## Current computer vision pipeline

### Intended pipeline

```
PDF/image → preprocess → OCR → layout → detect → segment → geometry
         → scale → measure → quantities
```

### Where it stops TODAY

| Stage | Status | Stops because |
|-------|--------|---------------|
| PDF/image ingest | **Works** | — |
| Preprocessing (rasterize/tiles) | **Works** | — |
| OCR (scale/title) | **Partial** | Optional deps; unproven accuracy |
| Layout understanding | **Missing** | No real layout model |
| Object detection | **Stops** | No weights |
| Segmentation | **Stops** | No weights; SAM2 unrouted |
| Geometry extraction | **Works on vector PDFs only** | Scanned plans have no vector segments |
| Scale detection | **Partial** | Manual works; OCR/fallback risky |
| Measurement | **Works if geometry+scale** | — |
| Quantity takeoff | **Works for vector rooms/walls** | Counts/symbols weak |

**Pipeline stop line:** After preprocessing for raster sheets — detection never produces real instances without `models/best.pt`. Vector sheets bypass CV entirely and jump to geometry measurement.

### Missing stages (spec)

| Missing stage | Input | Output | Recommended approach | Location | Difficulty | Testing |
|---------------|-------|--------|----------------------|----------|------------|---------|
| Layout / sheet regions | Raster page | Title block, plan viewport, legend | Deterministic + OCR; VLM later | `title_block_ocr.py`, new layout module | M | Fixtures |
| Room segmentation | Raster plan | Instance masks/polygons | Fine-tuned YOLO-seg or SAM2 assist | `inference/engine.py` | L–XL | Golden mIoU |
| Symbol detection | Raster / vector | Door/window/fixture boxes | Fine-tuned YOLO; vector heuristics bootstrap | `detect_symbols.py` | L | mAP |
| True wall centerlines | Raster or vectors | Polylines LF | Classical CV / geometry from rooms first | `wall_vectorization.py` | L | LF error % |
| Pattern search | User crop | Matches across sheets | CLIP patch / template match | `ai_routes` + UI | L | Retrieval@k |

---

## Current takeoff engine

### What works

| Capability | Implementation | Reliability |
|------------|----------------|-------------|
| PDF points → feet/sqft | `geometry/units.py` | High if `scale_ratio` correct |
| Room polygons from vectors | `vector_pdf.VectorPage` | High on clean vector plans |
| Wall LF + gypsum assumption | `quantities.py` (`WALL_HEIGHT_FT=9`) | Medium (height assumed) |
| PostGIS persist | `detection_geometry.py`, `geometry/postgis.py` | High (CI smoke) |
| Export quantities | `export_engine.py` | High |
| Manual scale calibrate | scale routes + UI | High |

### Weaknesses

| Area | Issue | Evidence |
|------|-------|----------|
| Scale | Silent default `96.0` | `_scale_ratio_for` in `takeoff_routes.py` |
| Raster units | Assumed 300 DPI | `preprocessing.py` |
| Manual measure | Missing on real sheets | Milestone 1 comments; no draw tools |
| Editing | Overlay non-interactive | `pointer-events-none` in `DrawingRenderer.jsx` |
| Counting | Heuristic / missing models | `vector_symbol_match`, `spatial_reasoning` estimates |
| Overlaps / duplicates | Not systematically handled | No IoU merge in product path |
| Snapping | Missing | — |
| Net vs gross | Incomplete vs Togal | quantities primitives limited |
| Rounding | ad hoc `round(..., 1)` | `quantities.py` |
| Precision | Vector exact; raster not | units module docs |

**Verdict:** The geometry math for vector PDFs is the strongest core asset in the repo. The product does **not** yet reliably do pixels → world units → trusted quantities for the general case (scans + human edit).

---

## Togal feature parity score

| Lens | Score |
|------|-------|
| Feature checklist breadth (A–AI matrix) | ~35–45% “touched”, ~17% fully implemented |
| **Core estimator loop** (upload→AI/manual takeoff→correct→export) | **~22–28%** |
| AI detection parity | **~0–5%** (code without weights) |
| Collaboration / chat / search shell | ~40% scaffolded, much partial |

See `TOGAL_PARITY_MATRIX.md` for per-feature status.

---

## Missing features

Highest-impact missing vs Togal public product:

1. Working automated AI takeoff on architectural scans (Togal button)  
2. Professional manual takeoff tool suite  
3. Editable AI results (accept/reject/edit on canvas)  
4. AI image search (bbox → find/count) in UI  
5. Pattern search  
6. Reliable auto-naming at plan-set scale  
7. Revision quantity deltas  
8. Grounded plan chat with citations  
9. Spec analysis / RFI workflow  
10. Recurring billing + enterprise SSO completion  

---

## Critical technical weaknesses

1. **No model weights** — AI path is non-functional by design until install (`models/README.md`).  
2. **Manual takeoff gap** — Phase 0 CLAUDE definition of done is unmet.  
3. **Signup broken** — `Signup.jsx` fake auth.  
4. **Mock UI residue** — Mock Sheets, dashboard fake stats, ChatWidget mocks, project fetch fallback to `SAMPLE_PROJECTS`.  
5. **Default scale** — silent wrong quantities.  
6. **Fake MEP estimates** mixed into “quantities”.  
7. **Spec drift** — `CLAUDE.md` ≠ repo (wastes agent effort).  
8. **Render free tier / no Redis in blueprint** — async/collab fragile.  
9. **SSO ACS 501**; integration tokens plaintext.  
10. **Zero frontend tests.**

---

## AI/ML gaps

### Models currently used (inventory)

| Model | Purpose | Input | Output | Where used | Train? | Fine-tune? | Accuracy evidence | Latency | GPU | Prod readiness |
|-------|---------|-------|--------|------------|--------|------------|-------------------|---------|-----|----------------|
| YOLOv8-seg (intended `best.pt`) | Room/space seg | Raster page/tiles | Masks/boxes → rooms | `InferenceEngine` | Yes | Yes | **None in repo** | N/A | Recommended | **Not ready** |
| YOLOv8-seg symbols | Doors/windows/MEP | Raster | Instances | `detect_symbols.py` | Yes | Yes | None | N/A | Recommended | **Not ready** |
| SAM2 | Zero-shot seg | Image + prompts | Masks | `sam2_zero_shot.py` (unrouted) | No (pretrained) | Optional | Unit tests only | High | Yes | **Experimental** |
| CLIP ViT-B/32 | Image embeddings | Tiles/crops | 512-d vectors | `clip_embeddings.py` | No | No | None at scale | Med | Optional | **Partial** |
| PaddleOCR | Scale text | Image crop | Text | `scale_detection.py` | No | No | Unproven | Med | No | **Partial** |
| Tesseract | Title block | Crop | Text fields | `title_block_ocr.py` | No | No | Unproven | Low | No | **Partial** |
| Claude (Anthropic) | Chat | Prompt + takeoff JSON | Text | `ai_routes` | No | No | None | API | No | **Partial** (key + model id) |
| ORB+RANSAC (OpenCV) | Align/diff | Two rasters | Diff image | `drawing_compare.py` | No | No | Heuristic | Med | No | **Partial** (needs cv2) |
| Vector geometry | Measure | PDF vectors | Rooms/walls/qty | `vector_pdf.py` | N/A | N/A | Unit + smoke tests | Low | No | **Strongest** |

### Missing AI capabilities (bucketed)

**PRE-TRAINED MODEL IS ENOUGH:** SAM2-assisted labeling; CLIP search; LLM chat with grounding; OCR engines.

**FINE-TUNING RECOMMENDED:** Room segmentation on AEC scans; door/window/fixture detectors.

**CUSTOM TRAINING REQUIRED:** Only if pursuing proprietary multi-trade symbol libraries at scale after fine-tunes plateau — **not** for MVP.

**DETERMINISTIC ALGORITHM SHOULD BE USED:** Vector PDF measure; scale from known dimension; quantity formulas; wall LF from polygons; export; overlap IoU merge.

**LLM/VLM SHOULD BE USED:** Chat, RFI drafts, optional title-block parsing assist — **not** primary measurement.

---

## Data gaps

- No labeled in-domain dataset in repo  
- No `best.pt` artifact  
- CorrectionEvent table ready but canvas HITL incomplete → flywheel starved  
- Public CubiCasa acquisition scripts exist but are not a substitute for AEC docs  
- Golden eval set not evidenced as populated  

See `AI_DATA_STRATEGY.md`.

---

## Infrastructure gaps

| Gap | Evidence |
|-----|----------|
| GPU inference not in deploy manifest | `render.yaml` API-only |
| Redis/Celery not in blueprint | Jobs/WS degrade |
| S3 optional | Local disk on free Render |
| Frontend has no test CI beyond build | `ci.yml` |
| Stripe one-time vs subscriptions | `mode="payment"` |
| Secrets hygiene | Plaintext integration tokens; demo seed passwords in docs |

---

## Top 20 blockers

| Rank | Pri | Blocker |
|------|-----|---------|
| 1 | P0 | No trained detection weights (`models/best.pt` missing) |
| 2 | P0 | Manual polygon/line/count tools missing on real sheets |
| 3 | P0 | Detection overlay not interactive (no accept/reject/edit) |
| 4 | P0 | Silent/default scale → wrong quantities |
| 5 | P0 | Signup does not call auth API |
| 6 | P0 | Scanned/raster plans have no working takeoff path |
| 7 | P0 | Rule-of-thumb MEP quantities pollute trusted exports |
| 8 | P0 | GPU inference service not deployed |
| 9 | P1 | No in-domain labeled dataset / golden eval set |
| 10 | P1 | Condition assignment only on demo canvas |
| 11 | P1 | Image search UI unwired; embeddings not indexed on upload |
| 12 | P1 | Mock Sheets / mock dashboard / mock chat erode trust |
| 13 | P1 | Redis/Celery absent from production blueprint |
| 14 | P1 | Symbol detector unused + unweighted |
| 15 | P1 | Revision compare lacks quantity-delta by condition |
| 16 | P1 | Chat not grounded to sheet regions; mock ChatWidget |
| 17 | P2 | Pattern search missing |
| 18 | P2 | Auto-naming OCR not production-grade |
| 19 | P2 | SSO ACS stub; invite email missing |
| 20 | P2 | No frontend tests; Stripe not real subscriptions |

---

## MVP definition

### Smallest demo for a professional estimator

**Must show:**

1. Account login (fix signup)  
2. Create project, upload construction drawings (vector PDF OK for v0)  
3. Process drawing (AUTODETECT or AI)  
4. Detect spaces / key objects  
5. Measurements with **confirmed scale**  
6. Quantities panel  
7. Manual correction (draw/edit/accept/reject)  
8. Save takeoff (PostGIS + TakeoffResult)  
9. Export Excel/CSV  

**Minimum build to achieve that (ordered):**

1. Fix signup + remove mocks from takeoff path  
2. Scale confirmation gate  
3. Manual tools + interactive overlay on `DrawingRenderer`  
4. Keep vector AUTODETECT as primary engine for demo  
5. Optional: one fine-tuned room model **or** SAM2-assisted flow for one scanned sample  
6. Export (already exists)  

### Do NOT build yet

- Spec analysis / RFI product  
- Pattern search  
- Full Liveblocks-style co-editing  
- Multi-trade MEP symbol libraries  
- Recreating Next.js monorepo from CLAUDE.md  
- Marketing accuracy claims (95–98%)  
- Pinecone or extra vector DBs (pgvector enough)  
- Custom foundation model training  
- India GTM expansions beyond what’s needed for core demo (unless that is the ICP)  

---

## Roadmap to parity

See `TOGAL_PARITY_ROADMAP.md` phases 1–10.

**Critical path:** Phase 1 honesty → Phase 2 manual HITL → Phase 3/4 CV+weights → then search/compare/chat polish.

---

## Recommended architecture

**Keep** the actual working architecture; update `CLAUDE.md` to match:

- Vercel static SPA (or migrate to Next later only if SSR/auth needs demand it)  
- FastAPI API on always-on workers (Render/Fly/AWS)  
- **Separate GPU inference service** (RunPod/Modal/AWS GPU) with HTTP contract `POST /infer`  
- Celery/Redis (or equivalent) for jobs — mandatory in prod  
- Postgres + PostGIS + pgvector on Neon/Supabase/Render  
- R2/S3 for files + tiles  
- JWT/org RBAC until SSO needed  

**Do not** run YOLO/SAM inside Vercel serverless.

---

## Recommended models

| Job | Model |
|-----|-------|
| Vector plans | Deterministic `vector_pdf` (already) |
| Interactive labeling / assisted seg | **SAM2** pretrained |
| Production rooms on scans | **YOLOv8/v11-seg** fine-tuned (matches existing engine) |
| Symbols | **YOLOv8** fine-tuned; geometric match as fallback |
| Search | **CLIP** ViT-B/32 (already) |
| OCR | PaddleOCR + Tesseract (already); don’t replace until eval fails |
| Chat | Current Claude/GPT via API with grounding — fix model id |
| Compare | OpenCV classical (already) |

---

## Recommended datasets

1. CubiCasa5K (bootstrap) via existing acquire script  
2. 100–300 in-domain A-series floor plans (manual annotate)  
3. 50–200 golden holdout with scale GT  
4. Production `CorrectionEvent` stream after HITL ships  

Details: `AI_DATA_STRATEGY.md`.

---

## Testing strategy

| Layer | Action |
|-------|--------|
| Geometry/units | Keep expanding pytest (already strongest) |
| Takeoff API | TestClient e2e with PostGIS (extend smoke) |
| Scale gate | Unit tests for blocked/unconfirmed scale |
| Frontend | Add Playwright: login→upload→autodetect→export |
| ML | Eval harness gates on golden set before ACTIVE |
| Never | Claim accuracy without golden measurement error report |

---

## Production readiness

| Area | Score (0–10) | Notes |
|------|--------------|-------|
| Frontend | 4 | Product pages real; mocks; no tests; signup broken |
| Backend | 6 | Broad real FastAPI surface; env-gated features |
| Database | 7 | Solid PostGIS/pgvector schema + Alembic |
| AI | 2 | Pipeline without weights = non-shipping |
| Computer Vision | 3 | Compare/preprocess real; detect not |
| OCR | 3 | Code present; unproven |
| Geometry | 7 | Vector engine is real strength |
| Takeoff | 4 | Vector yes; manual/AI no |
| Performance | 3 | Ideas (tiling) exist; ops weak |
| Security | 4 | Basic JWT; SSO stub; plaintext tokens |
| Scalability | 3 | Multi-tenant fields; single free Render |
| Testing | 5 | Backend unit strong; FE zero; AI e2e zero |
| UX | 3 | Estimator stuck without manual tools |
| Collaboration | 4 | WS/comments/shares; incomplete guest canvas |
| Exports | 6 | Excel/CSV/PDF real |
| Infrastructure | 3 | Partial deploy; no GPU/Redis in blueprint |
| **Overall** | **3.9** | Weighted toward takeoff-critical systems |

---

## Estimated engineering effort by phase

Effort is relative complexity (not calendar dates):

| Phase | Focus | Complexity |
|-------|-------|------------|
| 1 | Architecture honesty, signup, scale gate, mocks, Redis | **M** |
| 2 | Manual takeoff + HITL overlay | **L** |
| 3 | CV wiring, OCR batch, walls | **L** |
| 4 | Data + train + ship AI takeoff | **XL** (data-dominated) |
| 5 | Search index + bbox UI | **L** |
| 6 | Revision quantity deltas | **M–L** |
| 7 | Grounded chat / specs | **L–XL** |
| 8 | Collab depth + SSO | **L** |
| 9 | Prod infra, subs, FE e2e | **L** |
| 10 | Moat / eval / trade models | **XL** ongoing |

---

## Final recommendation

1. **Tell the truth in the product and the docs.** You have a strong **vector takeoff foundation**, not a Togal-equivalent AI platform. Update `CLAUDE.md` to the Vite/FastAPI stack or you will keep rebuilding the wrong thing.  
2. **Finish Phase 0 properly:** fix signup, kill mocks, **ship manual takeoff + interactive corrections**, enforce scale confirmation. Without this, AI weights will not produce a usable product.  
3. **Treat vector AUTODETECT as the demo engine** while you label data and train `best.pt`. Do not market raster AI until golden-set measurement error is measured.  
4. **Deploy GPU + install weights** only after HITL exists to capture `CorrectionEvent`s — that is the moat path already designed in schema.  
5. **Ignore feature sprawl** (pattern search, specs, SSO, 3D polish) until the loop `upload → measure → correct → export` is trustworthy on real estimator files.

**Bottom line:** TakeOff is a **STAGE 3 vector-powered takeoff MVP** with an unusually wide scaffold around it. The exact work to reach Togal-level capability is: **manual HITL + real detection models + scale discipline + production GPU/queue** — then search, compare depth, and chat. Everything else is secondary.
