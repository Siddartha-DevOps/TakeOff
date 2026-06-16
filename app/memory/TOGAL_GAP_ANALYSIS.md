# TakeOff vs Togal.AI — Gap Analysis & Build Roadmap

**Date:** 2026-06-16
**Purpose:** Honest audit of the current TakeOff repo against Togal.AI, the feature/module gaps to close, and an informed view of Togal.AI's likely tech & AI architecture.

---

## 1. What Togal.AI Actually Is (the product to match)

Togal.AI is a cloud-based **AI construction takeoff & estimating** platform. Core value: upload architectural plans, hit one button, and the AI auto-detects, measures, classifies, and counts building elements — turning hours/days of manual clicking into seconds, with a claimed ~98% accuracy on floor plans.

### Togal.AI feature set (the bar)
| Area | Capability |
|------|-----------|
| **Auto-takeoff** | One-click detection + measurement of spaces/areas, walls, objects, materials using AIA measurement standards |
| **Room/space AI** | Auto-classifies bedrooms, bathrooms, kitchens, mechanical, corridors; applies correct area math; organizes quantities by space type |
| **AI Search** | Image search, text search, and pattern search to instantly locate & count any element across a sheet/set |
| **Auto-naming & organization** | Upload, auto-name, and organize entire plan sets in minutes |
| **Compare / revisions** | Auto-compare drawing versions to surface changes between revisions |
| **Togal.CHAT** | Conversational AI to ask questions about the plans |
| **Manual tools** | Full manual takeoff toolkit (count, linear, area, polygon) to supplement/correct AI |
| **Trades coverage** | GC, concrete, drywall, painting, flooring, electrical, etc. — trade-specific outputs |
| **Collaboration** | Real-time multi-user takeoff in the cloud, role/permission sharing with subs |
| **Integrations** | Procore, PlanSwift, Bluebeam, eTakeoff (SnapAI), Excel export |
| **File support** | Vector PDF (best accuracy), raster JPEG/PNG/TIFF |
| **Platform** | Browser-based, any device; cloud storage of plan sets |

### Togal.AI's likely tech & AI architecture (inferred)
Togal does **not** publicly publish its stack, so the below is an informed inference from public statements ("computer vision + machine learning", "analyzed millions of plans", cloud SaaS, the integrations) plus standard industry patterns. Treat as a reference architecture, not confirmed fact.

- **Frontend:** SPA (React/TypeScript-class) with a high-performance plan canvas. Rendering vector PDFs at scale almost certainly uses a WebGL/canvas engine (PDF.js for vector extraction + a custom canvas/WebGL overlay for measurement vectors).
- **Backend:** Cloud API (Python is the natural fit for the ML stack; Node also plausible for the app tier) behind an API gateway, containerized (Docker/K8s) on a major cloud (AWS most likely).
- **AI/CV pipeline:**
  - **Vector parsing** of PDFs (extract line geometry, text, layers) — this is the secret sauce for "98% on vector PDFs": you measure real geometry, not pixels.
  - **Raster CV** for image-only plans: segmentation (room/space polygons), object detection (doors, windows, fixtures, symbols), and **OCR** for labels/dimensions/scale.
  - Model families: instance segmentation (Mask R-CNN / YOLO-seg / SAM-style) + detectors (YOLO/DETR) + OCR (PaddleOCR/Tesseract/cloud OCR) + embedding models (CLIP-style) powering **image/pattern search**.
  - **Togal.CHAT**: an LLM (RAG over the parsed drawing + detection results) — i.e., feed structured takeoff data + OCR text into an LLM as context.
- **Data:** Relational DB (Postgres) for projects/users/quantities; object storage (S3) for plan files & rendered tiles; a **vector database / pgvector** for similarity search; a queue (SQS/Celery/Kafka) for async inference jobs; GPU inference workers.
- **Scale/throughput:** async job queue + GPU autoscaling; tiled rendering of huge sheets; per-org multi-tenancy.

---

## 2. Current State of the TakeOff Repo (honest audit)

### Tech stack present
- **Frontend:** React 19 + Vite 8 + Tailwind 4, react-router 7, `react-pdf` (PDF.js), framer-motion, axios, lucide icons, sonner. Marketing site (Home/Features/Pricing/Comparison/Blog/About/Trades/Demo) + app (Dashboard, Takeoff workspace, Login/Signup, ProtectedRoute, AuthContext).
- **Backend:** FastAPI, SQLAlchemy 2 + **Postgres** (psycopg2) + Alembic, JWT auth (pyjwt/passlib/bcrypt), Stripe payments, Excel/CSV export (pandas), file uploads (aiofiles). **Also** a stray **MongoDB (motor)** connection in `server.py` used only for a throwaway `status_checks` collection.
- **AI (scaffolded):** `ai/detection_engine.py` (YOLOv8-seg via ultralytics), `preprocessing.py`, `scale_detection.py` (OCR), `spatial_reasoning.py`, `inference_api.py`, `ai_tasks.py` (Celery), CLIP image-search stub, `training/train.py`. Plus a thorough design doc (`AI_ARCHITECTURE_DESIGN.md`).

### What actually works today
- ✅ Auth (signup/login/JWT), projects CRUD, file upload to disk, drawing list, PDF/image rendering in the browser.
- ✅ Excel/CSV export endpoints, Stripe checkout scaffolding, marketing pages.
- ✅ A polished **takeoff UI** (layers, zoom/pan, quantities panel, chat panel, summary, confidence bars).

### What is mock / broken / not wired (the critical reality)
1. **The AI does not run.** AI libs (`ultralytics`, `torch`, `opencv`, `paddleocr`, `celery`, `clip`) are **not in `requirements.txt`**, so every AI import fails and the backend silently runs in "mock mode" (`server.py` try/except). **No trained model weights exist** (`best.pt` / `rooms_doors_windows_v1.pt` are absent), so even with libs installed, detection returns empty/fallback.
2. **The canvas shows fake data.** `Takeoff.jsx` calls `runTakeoffAI()` from `mock/mockAI.js` and draws detections on a **hardcoded SVG floor plan** (`CanvasFull`) — **not** on the uploaded drawing. The real `DrawingRenderer` (actual PDF) and the detection overlay are two separate, **unaligned** views. There is no coordinate mapping between AI pixel space and the rendered plan.
3. **Two conflicting route files.** `takeoff_routes.py` (uses `ai_engine.analyze`) and `ai_routes.py` (Celery + CLIP search + **real Claude chat**) overlap; `server.py` only mounts `takeoff_routes`, so the **CLIP image search and real Claude chat endpoints are never reachable**.
4. **Chat is mock.** Frontend `ChatPanel` uses `askTakeoffChat` (canned answers); the real Claude endpoint in `ai_routes.py` isn't wired into the UI or the app.
5. **No vector-PDF measurement.** Everything assumes raster CV; there is no PDF vector-geometry extraction — the single biggest accuracy lever Togal relies on.
6. **No manual takeoff tools, no edit-AI workflow.** The UI has "Accept/Edit" buttons that don't persist; there's no count/linear/area/polygon drawing tool.
7. **No scale calibration UI.** Scale is hardcoded `1/8"=1'-0"`; OCR scale detection isn't connected to a user-correctable calibration step.
8. **Dual DB confusion + no migrations applied.** Postgres models coexist with an unused Mongo; `Base.metadata.create_all` is used instead of Alembic migrations.

**Bottom line:** the repo is an excellent **prototype/sales demo + AI design spec**, but the core loop — *upload real plan → AI measures the actual drawing → user edits → trustworthy exportable quantities* — is **not functional end-to-end**.

---

## 3. Gap Analysis — Modules & Features to Build

Grouped by priority. Each item notes the gap and what "done" looks like.

### TIER 0 — Make the existing AI real (unblocks everything)
1. **Fix dependencies & model loading**
   - Add `ultralytics, torch, torchvision, opencv-python-headless, paddleocr, pillow, pdf2image, pymupdf, celery, redis, scikit-image` to `requirements.txt`.
   - Decide GPU vs CPU inference; document model weight location (S3 `AI_MODELS_BUCKET`).
2. **Train (or fine-tune) a real detection model**
   - Datasets: RPLAN, CubiCasa5K, FloorNet, Structured3D + your own annotated set (CVAT/Roboflow).
   - Start with YOLOv8-seg for rooms/doors/windows/fixtures; target ≥80% mAP@0.5 MVP.
3. **Align detections to the real drawing**
   - Replace the hardcoded `CanvasFull` SVG with an overlay layer rendered on top of `DrawingRenderer` (PDF.js page), using a single shared coordinate transform (pixel↔PDF point↔real-world feet).
4. **Wire async inference properly**
   - One canonical route module; Redis + Celery worker; status polling already exists (`processing_status`). Remove the duplicate route file.

### TIER 1 — The Togal "wow" core
5. **Vector-PDF geometry engine** *(highest-accuracy lever)*
   - Extract lines/polylines/text/layers from vector PDFs (PyMuPDF / pdfplumber). Snap measurements to real geometry instead of CV guesses. This is how you reach Togal-class accuracy on vector sets.
6. **Scale calibration module**
   - UI: user draws a known dimension or picks the scale; OCR auto-suggests; all areas/lengths derive from the calibrated ratio. Persist per-drawing.
7. **Manual takeoff toolkit** (must-have, AI is never 100%)
   - Tools: count/symbol, linear/length, area/polygon, rectangle, with snapping, real-world units, and live quantity rollups. Each manual item joins the same quantities table as AI items.
8. **Human-in-the-loop AI editing**
   - Accept/reject/relabel/resize/add detections; persist to a `detections`/`ai_corrections` table; feed corrections back into retraining (active learning loop already designed in the AI doc).
9. **Conditions / assemblies model**
   - Togal organizes quantities by "condition" (a named measured item with color, unit, formula). Add a `Condition` entity (name, trade, type, unit, color, waste %, formula) that both AI and manual measurements attach to.

### TIER 2 — Search, chat, compare
10. **AI Search (image + text + pattern)**
    - Build the CLIP embedding index (pgvector). Implement the stubbed `search/image` endpoint; add text search over OCR; add "find all like this" pattern/count search. Wire a search UI.
11. **Togal.CHAT equivalent**
    - Wire the **real** Claude endpoint (already written in `ai_routes.py`) into the UI, with RAG context = detections + OCR + quantities. Use the latest Claude model. Replace `askTakeoffChat` mock.
12. **Revision compare**
    - Diff two drawing versions (vector geometry diff or image diff + detection diff); highlight added/removed/changed elements. The UI already has a "Revisions" list to hang this on.

### TIER 3 — Make it a real multi-user SaaS
13. **Plan-set ingestion & auto-naming**
    - Multi-page PDF split into sheets; OCR title block to auto-extract sheet number/name/discipline; auto-organize the set. Today upload is single-file with manual `sheet_name`.
14. **Org/team collaboration & permissions**
    - `Organization` exists but there's no invite flow, roles (admin/estimator/viewer), sharing with subs, or real-time presence. Add team management + (eventually) live collaboration (WebSocket/CRDT).
15. **Real-time presence & comments**
    - The header shows fake avatars; build actual presence, comments/markups on the plan, notifications.
16. **Cloud file storage & big-sheet rendering**
    - Move uploads from local disk to **S3**; generate tiled/rasterized previews for huge sheets; CDN delivery.
17. **Billing → entitlements**
    - Stripe checkout exists but isn't connected to feature gating/usage limits (sheets/projects/seats per plan). Add subscription enforcement + webhooks → entitlements.
18. **Integrations**
    - Export/sync to Procore, PlanSwift, Bluebeam, and richer Excel templates (per-trade workbooks). Public API + webhooks.

### TIER 4 — Estimating layer (beyond takeoff)
19. **Cost/pricing database & estimate builder**
    - Map quantities → unit costs (material/labor) → priced estimate & proposal export. This is where "takeoff" becomes "estimating" and where revenue stickiness lives.
20. **Reporting & proposals**
    - Branded PDF proposals, bid summaries, scope-of-work generation (LLM-assisted).

### Cross-cutting hardening
21. **Data model migrations** (Alembic, drop the unused Mongo), **observability** (logging/metrics/tracing on inference), **security** (file scanning, signed URLs, tenant isolation tests), **testing/CI**, **rate limiting & job quotas**, **accuracy QA harness** (golden plan set with known quantities to measure regression).

---

## 4. Suggested Build Order (to get real, live users)

**Phase A — Functional core (make one drawing truly work):**
Tier 0 (1→4) → Tier 1 scale calibration (6) + manual tools (7) + detection alignment (3) + vector engine MVP (5).
Outcome: a user uploads a real plan, calibrates scale, the AI proposes measurements on the actual drawing, the user edits, and exports correct quantities. **This is the minimum that real users can trust.**

**Phase B — Differentiators:** conditions (9), HITL editing (8), AI search (10), real chat (11), revision compare (12).

**Phase C — SaaS readiness:** S3 + plan-set ingestion (13,16), teams/permissions (14), billing entitlements (17), integrations + estimating (18,19,20), plus all cross-cutting hardening (21).

---

## 5. One-line Summary
The repo already looks like Togal and has a credible AI *design*, but today it runs on **mock data with no trained model and overlays drawn on a fake floor plan**. The path to "real users" is: **make the AI actually run on the uploaded drawing, add scale calibration + manual tools + human-in-the-loop editing, then layer on vector-PDF accuracy, search, chat, compare, teams, storage, billing, and estimating.**

---

### Sources (Togal.AI research)
- https://www.togal.ai/ , https://www.togal.ai/features , https://www.togal.ai/how-it-works , https://www.togal.ai/trades/gc
- https://www.togal.ai/blog/ai-blueprint-reading-accuracy
- https://etakeoff.com/ai/ (SnapAI / Togal integration)
- https://insights.velocityaipartners.co/tools/togal-ai , https://www.aecplustech.com/tools/togal-ai
