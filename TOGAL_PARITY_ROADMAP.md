# TOGAL_PARITY_ROADMAP.md — Exact Path to Togal-Level Capability

**Audit date:** 2026-08-07  
**Current stage:** STAGE 3 — Functional Takeoff MVP (vector-PDF only; see `CTO_AUDIT.md`)  
**Constraint:** Build on the **actual** stack (Vite + FastAPI + PostGIS + Celery), not the aspirational Next.js monorepo in `CLAUDE.md`, unless a deliberate migration is funded.

Complexity scale: **S** (hours) · **M** (days of focused eng) · **L** (multi-week subsystem) · **XL** (multi-engineer / data-heavy)

---

## PHASE 1 — Fix current architecture

Goal: Make the existing product honest, usable, and deployable without fake paths.

| Priority | Feature | Why required | Current status | Files to modify | Dependencies | Complexity | Acceptance criteria | Testing |
|----------|---------|--------------|----------------|-----------------|--------------|------------|---------------------|---------|
| P0 | Fix signup to call real auth API | Users cannot create accounts | UI ONLY fake localStorage | `Signup.jsx`, optionally `AuthContext.jsx` | Working `/api/auth/signup` | S | Signup returns JWT; ProtectedRoute admits user; org created | API + manual e2e |
| P0 | Remove Mock Sheets / mock project fallbacks | Estimators click dead UI | Hardcoded sidebar + SAMPLE_PROJECTS fallback | `Takeoff.jsx`, `mockData.js` usage | Real drawings list API | S | Empty state only when no drawings; no silent mock project | Frontend manual |
| P0 | Mandatory scale before trusted quantities | Wrong default `96.0` poisons all numbers | Optional scale; silent default | `takeoff_routes.py`, `scale_routes.py`, Takeoff UI | Scale calibrate UI | M | Analyze/autodetect blocked or flagged until `scale_confirmed=true` | Unit + API tests |
| P0 | Align health semantics | `mock_mode` label lies | Health uses old name | `server.py` | None | S | Health reports `model_available: false` clearly | Unit |
| P1 | Redis + Celery in Render blueprint | Async AI/compare jobs unreliable | Not in `render.yaml` | `render.yaml`, docs | Redis add-on | M | Jobs process off web dyno | Deploy smoke |
| P1 | S3/R2 required in prod | Local disk dies on multi-instance | Optional | `storage.py`, env docs | Bucket credentials | S | Presign path only in production | Integration |
| P1 | Kill rule-of-thumb MEP in measured exports | Fake quantities destroy trust | `spatial_reasoning.py` estimates | `spatial_reasoning.py`, quantity builders | None | S | Exports contain only measured/detected items | Unit |
| P2 | Decide CLAUDE.md vs actual stack | Docs mislead every agent | Spec drift | `CLAUDE.md`, README | Product decision | S | Spec matches Vite/FastAPI or migration ticket filed | Doc review |

---

## PHASE 2 — Functional takeoff engine

Goal: Complete Phase-0 CLAUDE criteria: **manual measure on real sheets** + reliable quantities.

| Priority | Feature | Why required | Current status | Files to modify | Dependencies | Complexity | Acceptance criteria | Testing |
|----------|---------|--------------|----------------|-----------------|--------------|------------|---------------------|---------|
| P0 | Manual polygon / line / count tools on DrawingRenderer | Togal-class editing; only path when AI fails | MISSING (Milestone 1 comments) | `DrawingRenderer.jsx`, `annotations/*`, Takeoff toolbar | Annotation store | L | User draws area/line/count; values use calibrated scale; persist Detection/Measurement | Geometry unit + e2e |
| P0 | Clickable detection overlay (accept/reject/edit) | CorrectionEvent flywheel; human-editable AI | Overlay `pointer-events-none` | `DrawingRenderer.jsx`, correction UI, `correction_routes.py` | Manual tools | L | Accept/reject/relabel writes `CorrectionEvent`; geometry editable | API + UI |
| P0 | Condition assignment on real sheets | Classify quantities into trades | Only on demo CanvasFull | Takeoff conditions panel + store | Overlay interactivity | M | Drag/select → condition; quantities panel updates | E2E |
| P1 | Snapping / vertex edit / delete | Professional estimator expectation | Missing | annotations geometry | Manual tools | M | Snap to endpoints; edit vertices; undo | Unit geometry |
| P1 | Net vs gross area modes | Togal exposes GSF/NSF variants | Partial | `quantities.py`, UI | Vector rooms | M | Toggle modes; export labels correct | Unit |
| P1 | Duplicate / overlap detection | Prevent double-count | Missing | geometry helpers | Detections | M | Flag IoU>threshold overlaps | Unit |
| P2 | India units polish | Existing moat code | Partial | `geometry/india_units.py`, BOQ | Scale | S | sqm/rm consistent | Existing tests |

---

## PHASE 3 — Computer vision

Goal: Make raster/scanned plans processable end-to-end (still may need fine-tuned weights in Phase 4).

| Priority | Feature | Why required | Current status | Files to modify | Dependencies | Complexity | Acceptance criteria | Testing |
|----------|---------|--------------|----------------|-----------------|--------------|------------|---------------------|---------|
| P0 | Wire SAM2 or YOLO path with installable weights contract | Scanned plans currently dead | Engine real; weights absent; SAM2 unrouted | `takeoff_routes.py`, `sam2_zero_shot.py`, `models/`, GPU Dockerfile | GPU host, Phase 1 queue | L | Upload scan → job → detections persisted OR clear failure | Integration w/ fixture weights |
| P0 | Preprocessing standardization | DPI/scale consistency | 300 DPI assume | `preprocessing.py` | Scale gate | M | Record render DPI on Drawing; conversions use it | Unit |
| P1 | Title-block OCR batch at upload | Auto-naming / organize | Partial | `title_block_ocr.py`, upload pipeline | Tesseract in image | M | Sheet number/title filled for ≥N fixture title blocks | OCR fixtures |
| P1 | Wall line extraction improvement | Wall LF accuracy | Adjacency heuristic | `wall_vectorization.py` or CV line detector | Rooms | L | Eval wall LF error on golden set | Eval harness |
| P2 | OpenCV in API or dedicated worker | Compare 503s without cv2 | Optional dep | Dockerfile / worker | Phase 1 Redis | M | Compare always available | CI |

---

## PHASE 4 — AI takeoff

Goal: Credible “Togal button” for architectural floor plans.

| Priority | Feature | Why required | Current status | Files to modify | Dependencies | Complexity | Acceptance criteria | Testing |
|----------|---------|--------------|----------------|-----------------|--------------|------------|---------------------|---------|
| P0 | Train + ship `models/best.pt` (rooms) | Core differentiator | No weights | `training/`, `ml/training/`, model registry | Labeled data (see `AI_DATA_STRATEGY.md`) | XL | Golden set mIoU gate (e.g. ≥0.70) before ACTIVE | `ml/eval/*` |
| P0 | Train symbol/count model | Doors/fixtures counts | No weights | `detect_symbols.py`, training | Symbol annotations | XL | mAP@0.5 gate on doors/windows | Eval |
| P0 | One-click AI takeoff UX | Match Togal button mental model | Split autodetect/analyze | Takeoff.jsx, takeoff_routes | Models + scale gate | M | One button: vector if possible else raster AI; progress; quantities | E2E |
| P1 | Confidence UI + filter | Estimators trust selectively | Partial confidence fields | Overlay + quantities | Models | M | Filter low-conf; bulk accept high-conf | UI |
| P1 | Promote via ModelVersion | Prevent silent regressions | Registry code exists | `eval_routes.py`, `ml/eval/promote.py` | Eval harness | M | Only ACTIVE model served | Tests exist — extend |
| P2 | Fine-tune from CorrectionEvent | Moat | Export scripts exist | `ml/training/export_corrections.py`, retrain | Production corrections | L | Retrain job consumes corrections | Pipeline test |

---

## PHASE 5 — Search

| Priority | Feature | Why required | Current status | Files to modify | Dependencies | Complexity | Acceptance criteria | Testing |
|----------|---------|--------------|----------------|-----------------|--------------|------------|---------------------|---------|
| P1 | Index tiles with CLIP on upload | Image search inert | Backend only | `clip_embeddings.py`, Celery task | torch+CLIP worker | L | Embeddings rows after upload | Integration |
| P1 | BBox image search UI | Togal signature feature | `searchAPI.image` unused | Takeoff canvas + search panel | Indexing | M | Draw box → matches across sheets with counts | E2E |
| P1 | Plan-set text search + highlight | Find notes/tags | Partial text search | ai_routes, OCR index, UI | OCR | M | Query jumps to sheet+region | E2E |
| P2 | True pattern search | Count repeating symbols | Missing | New matcher or few-shot | Image search | L | Crop → N matches with IoU check | Eval set |

---

## PHASE 6 — Drawing comparison

| Priority | Feature | Why required | Current status | Files to modify | Dependencies | Complexity | Acceptance criteria | Testing |
|----------|---------|--------------|----------------|-----------------|--------------|------------|---------------------|---------|
| P1 | First-class RevisionSet | Heuristic sheet_name grouping weak | Partial | `models.py`, compare_routes, UI | Upload flow | M | Upload rev B linked to rev A | API |
| P1 | Quantity delta by condition | Estimators need scope change $ | Visual diff only | `drawing_compare.py`, export | Takeoffs on both revs | L | Export added/removed LF/SF/counts | Unit + e2e |
| P2 | Manual control-point align | ORB fails on sparse scans | Optional manual points already in API | CompareModal UI | compare API | M | User sets 3+ points; align improves | Manual |

---

## PHASE 7 — AI document assistant

| Priority | Feature | Why required | Current status | Files to modify | Dependencies | Complexity | Acceptance criteria | Testing |
|----------|---------|--------------|----------------|-----------------|--------------|------------|---------------------|---------|
| P1 | Fix chat model + remove mock ChatWidget | Trust | Partial + mock widget | `ai_routes.py`, `ChatWidget.jsx` | ANTHROPIC_API_KEY | S | No canned marketing answers in product shell | UI |
| P1 | Grounded citations (sheet, bbox) | Togal.CHAT usefulness | JSON context only | ai_routes, ChatPanel | Search index | L | Every claim cites evidence or abstains | Eval prompts |
| P2 | Spec PDF ingestion | Spec analysis missing | Missing | New ingest + embeddings | Storage | XL | Ask spec question with clause cite | Integration |
| P2 | RFI draft object | Workflow | Missing | models + routes + UI | Chat | M | Save/export RFI markdown | API |

---

## PHASE 8 — Collaboration

| Priority | Feature | Why required | Current status | Files to modify | Dependencies | Complexity | Acceptance criteria | Testing |
|----------|---------|--------------|----------------|-----------------|--------------|------------|---------------------|---------|
| P1 | Guest SharedView canvas | External collab incomplete | Sheet list only | `SharedView.jsx` | Share tokens | M | Viewer sees drawing + quantities | E2E |
| P1 | Email invites | Team growth | Tokens only | team_routes + email provider | Resend/SES | M | Invite email delivered | Integration |
| P2 | Co-edit annotations | Real-time takeoff | Presence only | realtime + CRDT or OT | WS | XL | Two users edit without clobber | Multi-client |
| P2 | Complete SAML ACS | Enterprise | 501 stub | `sso_routes.py` | IdP | L | Login via Okta/Azure AD | Staging |

---

## PHASE 9 — Production infrastructure

| Priority | Feature | Why required | Current status | Files to modify | Dependencies | Complexity | Acceptance criteria | Testing |
|----------|---------|--------------|----------------|-----------------|--------------|------------|---------------------|---------|
| P0 | GPU inference service deployed | Raster AI | Dockerfile only | infra, Render/RunPod/Modal | Weights | L | Separate GPU URL; API enqueues | Load test |
| P1 | Stripe Subscriptions | Billing truth | One-time payment | `stripe_routes.py` | Stripe | M | Recurring + portal | Webhook tests |
| P1 | Encrypt integration secrets | Security | Plaintext | models + crypto helper | KMS/app key | M | Tokens at rest encrypted | Unit |
| P1 | Frontend tests + critical e2e | Regressions | No FE tests | frontend test setup | Playwright | L | Upload→autodetect→export passes CI | CI |
| P2 | Observability dashboards | Ops | Sentry optional | Sentry + metrics | — | M | Error budget visible | — |
| P2 | SOC2-oriented audit log UI | Enterprise | ActivityLog exists | audit UI | — | M | Admin can filter events | API |

---

## PHASE 10 — Model/data moat

| Priority | Feature | Why required | Current status | Files to modify | Dependencies | Complexity | Acceptance criteria | Testing |
|----------|---------|--------------|----------------|-----------------|--------------|------------|---------------------|---------|
| P0 | Production CorrectionEvent → dataset pipeline | Moat | Export scripts | `ml/training/export_corrections.py`, labeling | HITL UI | L | Weekly dataset version from prod | Pipeline |
| P1 | Golden eval set ≥200 sheets | Gate promotions | Harness exists; set thin | `ml/eval/`, `ml/datasets/` | Annotation | XL | Promotion blocked if metrics drop | CI eval job |
| P1 | Trade-specific fine-tunes | Multi-trade parity | Single class map | training configs | Data | XL | Per-trade ACTIVE models | Eval |
| P2 | Active learning queue in daily ops | Label efficiency | Code + AIDashboardModal | `ml/active_learning/*` | Prod traffic | M | Review queue triaged weekly | Process |
| P2 | India DSR/SOR real ratebooks | Regional moat | Sample rates | `estimating/ratebook.py` | Licensed data | L | Customer ratebook import | Tests |

---

## Suggested build order (critical path)

```
Phase 1 (honesty + scale gate + signup)
  → Phase 2 (manual takeoff + HITL on real sheets)
    → Phase 3/4 (CV + trained models) in parallel with data labeling
      → Phase 5 search
        → Phase 6 revision deltas
          → Phase 7–8 chat/collab
            → Phase 9–10 harden + moat
```

**Do not** start Phase 5–8 polish before Phase 2 manual tools and Phase 4 weights — that is how the repo accumulated a wide shell with a broken core loop.
