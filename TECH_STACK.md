# TECH_STACK.md — TakeOff.ai Actual Technology Stack

**Audit date:** 2026-08-07  
**Source of truth:** live repository at `/workspace` (not `CLAUDE.md` aspirations)  
**Product name:** TakeOff / TakeOff.ai

> `CLAUDE.md` describes a Next.js 14 / Turborepo / Clerk / Inngest monorepo.  
> **That architecture is not what is in this repo.** The actual product is a Vite React SPA + FastAPI monolith with optional Celery/Redis and a separate CUDA inference Dockerfile.

---

## Frontend

| Item | Actual |
|------|--------|
| Framework | **React 19** + **Vite 8** SPA (`app/frontend/`) |
| Language | **JavaScript/JSX** (no TypeScript) |
| Routing | `react-router-dom` v7 (`App.jsx`) |
| Styling | **Tailwind CSS v4** + PostCSS |
| UI kit | No shadcn; Lucide icons; Sonner toasts |
| State | Custom hooks (`useAnnotationStore`); **no Zustand, no TanStack Query** |
| PDF viewer | `react-pdf` (PDF.js) |
| Large image / tiles | **OpenSeadragon** 6 |
| Overlay / draw | Custom SVG overlays — **no Konva, no Fabric.js** |
| 3D | **Three.js** (`Drawing3DView.jsx`) |
| HTTP | Axios (`services/api.js`) |
| Motion | Framer Motion (marketing) |
| Tests | **None** (`npm test` exits 1) |
| Deploy | **Vercel** static (`vercel.json` → `app/frontend/dist`) |

**Not present despite CLAUDE.md:** Next.js App Router, TypeScript, Zustand, TanStack Query, shadcn/ui, Konva/Fabric, Clerk/Auth.js.

---

## Backend

| Item | Actual |
|------|--------|
| Framework | **FastAPI** (`app/backend/server.py`) |
| Language | **Python 3.11** |
| ORM | **SQLAlchemy 2** + **Alembic** migrations |
| API style | REST route modules under `app/backend/routes/` |
| Auth | Custom **JWT** (python-jose) + **bcrypt** (passlib) — **not Clerk** |
| Async jobs | **Celery 5** + Redis, with FastAPI `BackgroundTasks` fallback |
| Realtime | Custom **WebSockets** + Redis presence (`realtime.py`) |
| Deploy | **Render** Docker (`render.yaml` → `takeoff-api.onrender.com`) |
| API proxy | Vercel rewrites `/api/*` → Render |

---

## Database

| Item | Actual |
|------|--------|
| Engine | **PostgreSQL** (Render managed / local CI Postgres 16) |
| Spatial | **PostGIS** via GeoAlchemy2 (`Detection.geom`, `Measurement.geom`, SRID 0) |
| Vectors | **pgvector** (`DrawingEmbedding.embedding` Vector(512), HNSW) |
| Schema | `app/backend/models.py` (~793 LOC) + Alembic versions |
| Seed | `seed.py` / `SEED_ON_START` (demo users) |

Core entities present: `Organization`, `User`, `Project`, `Drawing` (sheet), `Condition`, `Detection`, `Measurement`, `TakeoffResult`, `CorrectionEvent`, `ModelVersion`, `DrawingEmbedding`, billing, comments, shares, assemblies, estimates, SSO config, activity log.

---

## Storage

| Item | Actual |
|------|--------|
| Object storage | **S3-compatible** (Cloudflare R2 / AWS S3) via boto3 (`storage.py`) |
| Presigned upload | Yes (`generate_presigned_upload` + `/uploads/presign` + `/confirm`) |
| Fallback | **Local disk** when `S3_BUCKET` unset |
| Tiles | Server-side tile generation for OpenSeadragon (`tiling.py`) |

---

## Authentication

| Item | Actual |
|------|--------|
| Primary | Email/password → JWT Bearer (`auth.py`, `auth_routes.py`) |
| Orgs / roles | `Organization` + `User.role` (`OWNER/ADMIN/MEMBER/VIEWER`) |
| Invites | Token accept flow (`team_routes`) — **no email delivery** |
| SSO | SAML AuthnRequest scaffold; **ACS returns HTTP 501** (`sso_routes.py`) |
| OAuth social | Login UI buttons present — **no handlers** |
| Signup page | **Broken / fake** — writes `localStorage.takeoff_user`, never calls API (`Signup.jsx`) |

---

## AI models

| Model / component | Status in repo |
|-------------------|----------------|
| YOLOv8-seg spaces (`models/best.pt`) | **Code present, weights ABSENT** (`models/` = `.gitkeep` only) |
| YOLOv8-seg symbols (`ai/models/symbol_counts/`) | **Code present, weights ABSENT** |
| SAM2 zero-shot (`ai/sam2_zero_shot.py`) | **Implemented, NOT wired to any API route** |
| OpenAI CLIP ViT-B/32 (`clip_embeddings.py`) | **Code present**; needs torch+CLIP at runtime |
| Anthropic Claude (TakeOff.CHAT) | HTTP call when `ANTHROPIC_API_KEY` set; model id `"claude-sonnet-5"` suspicious |
| Spatial reasoning heuristics | Rule-of-thumb MEP estimates (`spatial_reasoning.py`) |
| Vector-PDF AUTODETECT | **Deterministic geometry** — not an ML model (`geometry/vector_pdf.py`) |

**Trained `.pt` / `.pth` / `.onnx` files in repository: zero.**

---

## OCR

| Tool | Where | Purpose |
|------|-------|---------|
| **PaddleOCR** | `ai/scale_detection.py` (via ML deps) | Scale text / graphic bar |
| **pytesseract** | `ai/title_block_ocr.py` | Title-block sheet number / discipline / title |
| Graceful degrade | Both paths | Placeholder titles / OCR skip if binaries missing |

---

## Computer vision

| Capability | Implementation |
|------------|----------------|
| PDF → raster | PyMuPDF / pdf2image @ ~300 DPI (`ai/preprocessing.py`) |
| Inference engine | `ai/inference/engine.py` — tiled YOLO, device-aware |
| Symbol detection | `ai/detect_symbols.py` |
| Wall vectorization | Geometric adjacency heuristic (`ai/wall_vectorization.py`) — not a wall CNN |
| Drawing compare | OpenCV ORB + RANSAC (`drawing_compare.py`) |
| Vector symbol match | Geometric heuristics (`geometry/vector_symbol_match.py`) |
| GPU image | `ai/inference/Dockerfile` (CUDA 12.1) — separate from API image |

---

## Vector database

| Item | Actual |
|------|--------|
| Store | **pgvector** inside Postgres |
| Embedding dim | 512 (CLIP ViT-B/32) |
| Index | HNSW cosine on `drawing_embeddings` |
| Separate vector DB (Pinecone/Weaviate/etc.) | **Not used** |

---

## Search

| Mode | Backend | Frontend |
|------|---------|----------|
| Text search | `ai_routes` + CLIP/OCR path | Wired (`searchAPI.text`) |
| Count / pattern-like | `searchAPI.count` | Wired |
| Image (bbox → search) | Backend route exists | **UI never calls `searchAPI.image`** |
| Full RAG over tiles | **Missing** — chat uses structured takeoff JSON, not tile embeddings |

---

## Cloud

| Layer | Provider |
|-------|----------|
| Frontend host | **Vercel** |
| Backend host | **Render** (Docker free plan in `render.yaml`) |
| Database | Render Postgres (blueprint) / Neon-compatible URL pattern |
| Object storage | S3/R2 (env-configured) |
| Redis | Required for Celery + WS; not defined in `render.yaml` blueprint |

---

## GPU

| Item | Actual |
|------|--------|
| Inference host | Intended: CUDA Docker (`ai/inference/Dockerfile`) |
| Modal / Replicate / RunPod wiring | **Not present as live integrations** (training docs mention Colab/RunPod) |
| Production GPU service | **Not deployed in this repo’s infra manifests** |
| Behavior without GPU/weights | `ModelUnavailableError` — fail closed; vector `/autodetect` still works |

---

## Queues

| Item | Actual |
|------|--------|
| Broker | **Celery** + **Redis** (`celery_app.py`) |
| Fallback | FastAPI `BackgroundTasks` when Celery unavailable |
| Inngest / Trigger.dev / QStash | **Not used** |
| Completion | Internal webhook (`webhook_routes.py`) |

---

## Payments

| Item | Actual |
|------|--------|
| Provider | **Stripe** (`stripe_routes.py`) |
| Mode | Checkout `mode="payment"` (**one-time**, not recurring subscription) |
| Entitlements | Plan caps on projects + AI takeoffs (`entitlements.py`) |
| Plans | free / starter / growth / business |

---

## Monitoring

| Item | Actual |
|------|--------|
| Errors | **Sentry** optional (`observability.py` + `SENTRY_DSN`) |
| Analytics | Vercel Analytics **not wired in frontend code** |
| Celery | Flower listed in ML requirements |
| Logging | loguru / std logging |

---

## Testing

| Layer | Actual |
|-------|--------|
| Backend | **~48 pytest modules**, ~329 tests — strong unit coverage of geometry, units, inference partitioning, auth, estimating |
| Integration | CI runs Alembic + pytest + `scripts/smoke_test.py` against real PostGIS |
| Frontend | **No tests** |
| GPU / weights e2e | **None** (no weights in tree) |
| CI | `.github/workflows/ci.yml` — backend-e2e + frontend-build |

---

## CI/CD

| Item | Actual |
|------|--------|
| CI | GitHub Actions (`ci.yml`) on `main` + PRs |
| Frontend CD | Vercel (inferred from `vercel.json`) |
| Backend CD | Render Blueprint (`render.yaml`) |
| Migrations on boot | `alembic upgrade head` in Docker `start.sh` |

---

## Stack summary (one screen)

```
Browser (React/Vite/Tailwind)
    → Vercel static + /api rewrite
        → FastAPI on Render
            → Postgres + PostGIS + pgvector
            → S3/R2 (or local disk)
            → Redis + Celery (optional)
            → (optional) CUDA YOLO inference container
            → Stripe / Anthropic / Sentry (env-gated)
```

**Primary working takeoff path today (no ML weights required):**

```
Vector PDF upload → scale calibrate → POST /autodetect
  → geometry/vector_pdf.measure_pdf → quantities → PostGIS → Excel/CSV export
```
