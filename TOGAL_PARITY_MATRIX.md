# TOGAL_PARITY_MATRIX.md — TakeOff vs Togal.AI

**Audit date:** 2026-08-07  
**TakeOff source of truth:** live code under `app/`  
**Togal source of truth:** public product pages ([togal.ai/features](https://www.togal.ai/features), [togal.ai](https://togal.ai/), [trades](https://www.togal.ai/trades), help/editor walkthrough, third-party reviews)

### Status legend

| Status | Meaning |
|--------|---------|
| **IMPLEMENTED** | End-to-end path exists and can work with correct env (no fake data) |
| **PARTIALLY IMPLEMENTED** | Real code path, but incomplete, ungated, or fails without missing deps/weights |
| **UI ONLY** | Visible UI / marketing; no real backend behavior for that feature |
| **BACKEND ONLY** | Backend exists; frontend never wires it for the user |
| **EXPERIMENTAL** | Code/tests exist; not production-routed or unproven |
| **MISSING** | Not present in a meaningful form |

### Togal public capability baseline (what we compare against)

Togal markets: cloud takeoff; green **Togal button** auto takeoff (footprint/GSF, gross/net room areas, wall LF, counts for doors/fixtures/appliances/furniture on architectural floor plans & RCPs); advanced **manual** edit tools (split/cut/merge/arc); **AI image / text / pattern search**; **auto-naming** of sheets; **drawing/revision comparison**; **Togal.CHAT** (query plans, RFI/RFP help); **real-time collaboration**; **3D viewer**; **export** to Excel / estimating tools; multi-trade coverage; claimed ~98% accuracy / ~5× speed (marketing — not treated as measured truth here).

---

## Overall parity score

| Metric | Value |
|--------|-------|
| Categories scored (A–AI) | 35 |
| Fully IMPLEMENTED | **6** (~17%) |
| PARTIALLY / EXPERIMENTAL / BACKEND ONLY | **19** (~54%) |
| UI ONLY / MISSING | **10** (~29%) |
| **Weighted parity vs Togal core estimator loop** | **~22–28%** |
| Core AI takeoff (Togal button equivalent on scanned plans) | **~0% working** (no weights) |

---

## A. Drawing ingestion

| Field | Detail |
|-------|--------|
| **Status** | **IMPLEMENTED** |
| **Relevant files** | `app/frontend/src/components/FileUploadZone.jsx`, `app/backend/routes/upload_routes.py`, `app/backend/storage.py` |
| **Functions** | `uploadsAPI.uploadDrawing`, `generate_presigned_upload`, local multipart fallback |
| **Quality** | Solid: PDF/image upload, presign→confirm, local fallback when S3 absent |
| **Technical debt** | Dual path (local vs S3) complicates path resolution; tile regen unused in UI |
| **Production needs** | Always-on R2/S3, virus/size limits, multi-page plan-set batch UX polish |

---

## B. PDF/image processing

| Field | Detail |
|-------|--------|
| **Status** | **PARTIALLY IMPLEMENTED** |
| **Relevant files** | `geometry/vector_pdf.py`, `ai/preprocessing.py`, `tiling.py`, `DrawingRenderer.jsx` |
| **Functions** | `extract_page_geometry`, `measure_pdf`, rasterize @ 300 DPI, OpenSeadragon tiles |
| **Quality** | Vector path is strong; raster path exists but useless without weights |
| **Technical debt** | Scanned PDFs correctly rejected by vector gate (`MIN_VECTOR_SEGMENTS=12`) then fall into broken AI path |
| **Production needs** | Robust multi-page PDF split, CAD support, progressive tile pipeline on Render workers |

---

## C. OCR

| Field | Detail |
|-------|--------|
| **Status** | **PARTIALLY IMPLEMENTED** |
| **Relevant files** | `ai/scale_detection.py`, `ai/title_block_ocr.py`, `routes/scale_routes.py`, `routes/plan_set_routes.py` |
| **Functions** | Scale pattern OCR, graphic bar heuristic, `extract_title_block` (pytesseract) |
| **Quality** | Real code with graceful degrade; accuracy unproven in CI (no OCR e2e with fixtures) |
| **Technical debt** | Dual OCR stacks (Paddle + Tesseract); placeholder titles when OCR fails |
| **Production needs** | Fixture-based OCR eval; title-block model or rules tuned on real title blocks |

---

## D. Sheet classification

| Field | Detail |
|-------|--------|
| **Status** | **PARTIALLY IMPLEMENTED** |
| **Relevant files** | `plan_organizer.py`, `title_block_ocr.py`, `routes/plan_set_routes.py`, `ClassificationModal.jsx`, `routes/classification_routes.py` |
| **Functions** | Discipline/sheet fields on `Drawing`; classification templates CRUD/apply |
| **Quality** | DB + UI for templates; auto classification depends on OCR success |
| **Technical debt** | Not a trained sheet-type classifier |
| **Production needs** | Reliable title-block parsing + user confirmation UX at upload |

---

## E. Auto naming

| Field | Detail |
|-------|--------|
| **Status** | **PARTIALLY IMPLEMENTED** |
| **Relevant files** | `ai/title_block_ocr.py`, `plan_organizer.py`, `PlanSetModal.jsx` |
| **Functions** | OCR → sheet_number / title / discipline; manual edit in plan set UI |
| **Quality** | Far below Togal “name hundreds of sheets in seconds” — OCR optional and fragile |
| **Technical debt** | Placeholder sheet titles; no batch auto-rename confidence UI |
| **Production needs** | Batch OCR job + review grid + rename apply |

---

## F. Drawing organization

| Field | Detail |
|-------|--------|
| **Status** | **PARTIALLY IMPLEMENTED** |
| **Relevant files** | `PlanSetModal.jsx`, `routes/plan_set_routes.py`, `models.Drawing` plan-set fields |
| **Functions** | Page/sheet/discipline metadata; plan set get/update |
| **Quality** | Basic organization exists |
| **Technical debt** | Takeoff sidebar still shows hardcoded “Mock Sheets” with no-op buttons (`Takeoff.jsx`) |
| **Production needs** | Replace mock sheets list; drag-reorder; filters by discipline |

---

## G. Object detection

| Field | Detail |
|-------|--------|
| **Status** | **BACKEND ONLY** / **EXPERIMENTAL** (effectively **MISSING** in production) |
| **Relevant files** | `ai/inference/engine.py`, `ai/detect_symbols.py`, `ai/detection_engine.py`, `models/README.md` |
| **Functions** | `InferenceEngine.analyze`, `ModelUnavailableError`, symbol YOLO path |
| **Quality** | Engine is real and fail-closed; **zero `.pt` weights in repo** |
| **Technical debt** | Dead `BlueprintDetector` path; health still labels unloaded as `mock_mode` |
| **Production needs** | Trained weights + GPU host + promotion via `ModelVersion` |

---

## H. AI takeoff

| Field | Detail |
|-------|--------|
| **Status** | **PARTIALLY IMPLEMENTED** (vector) / **MISSING** (raster AI) |
| **Relevant files** | `routes/takeoff_routes.py` (`autodetect_drawing`, `analyze_drawing`), `geometry/quantities.py`, `Takeoff.jsx` |
| **Functions** | `/autodetect` → `measure_pdf` → Area/Line/Count; `/analyze` → Celery → YOLO (needs weights) |
| **Quality** | Vector AUTODETECT is the only credible “one-click” path today |
| **Technical debt** | Frontend prefers autodetect then analyze; scanned plans hit unavailable banner |
| **Production needs** | Working room/wall/door/fixture models; HITL edit; scale required gate |

---

## I. Manual takeoff

| Field | Detail |
|-------|--------|
| **Status** | **MISSING** on real sheets (**PARTIAL** store only) |
| **Relevant files** | `annotations/useAnnotationStore.js`, `annotations/types.js`, `DrawingRenderer.jsx` |
| **Functions** | Store supports `addAnnotation` / meta; comments say “Milestone 1” for edit; overlay `pointer-events-none` |
| **Quality** | Annotation model designed; **no polygon/line/count draw tools on OpenSeadragon** |
| **Technical debt** | Unavailable-AI banner promises “manual takeoff tools” that do not exist |
| **Production needs** | Konva/Fabric or custom OSD drawer: poly, line, count, edit, delete, snap |

---

## J. Measurement

| Field | Detail |
|-------|--------|
| **Status** | **PARTIALLY IMPLEMENTED** |
| **Relevant files** | `geometry/units.py`, `geometry/vector_pdf.py`, `ai/preprocessing.py`, `routes/scale_routes.py` |
| **Functions** | `points_to_feet`, `sqpoints_to_sqfeet`, `pixels_to_feet`, scale calibrate |
| **Quality** | Exact for vector PDFs when scale correct; raster depends on assumed 300 DPI |
| **Technical debt** | Default `scale_ratio=96.0` if unset (`_scale_ratio_for`) silently wrong for many sheets |
| **Production needs** | Hard block AI/measure without confirmed scale; unit system preference |

---

## K. Counting

| Field | Detail |
|-------|--------|
| **Status** | **PARTIALLY IMPLEMENTED** |
| **Relevant files** | `geometry/vector_symbol_match.py`, `geometry/quantities.py`, `ai/detect_symbols.py`, `ai/spatial_reasoning.py` |
| **Functions** | Vector symbol heuristics; room counts; rule-of-thumb MEP estimates |
| **Quality** | Space counts from vector rooms are real; door/fixture counts weak/heuristic; YOLO counts need weights |
| **Technical debt** | `spatial_reasoning` invents outlet/fixture estimates from area formulas |
| **Production needs** | Symbol detector + user confirm; kill rule-of-thumb from “measured” exports |

---

## L. Area calculations

| Field | Detail |
|-------|--------|
| **Status** | **IMPLEMENTED** (vector path) |
| **Relevant files** | `geometry/vector_pdf.py`, `geometry/quantities.py`, `geometry/postgis.py` |
| **Functions** | Room polygons → sqft; PostGIS `ST_Area` in smoke test |
| **Quality** | Strong for closed vector faces |
| **Technical debt** | Net vs gross vs wall-included areas not fully Togal-parity; assumed 9 ft wall height for gypsum |
| **Production needs** | Explicit GSF / NSF / wall-included modes; openings subtraction |

---

## M. Linear measurements

| Field | Detail |
|-------|--------|
| **Status** | **PARTIALLY IMPLEMENTED** |
| **Relevant files** | `vector_pdf.py`, `wall_vectorization.py`, `quantities.py` |
| **Functions** | Wall LF from vector segments / room adjacency centerlines |
| **Quality** | Useful for vector plans; walls from room edges ≠ true wall centerlines on complex plans |
| **Technical debt** | No arc tool; no multi-segment polylines in UI |
| **Production needs** | Manual linear tool + better wall extraction |

---

## N. Quantity calculations

| Field | Detail |
|-------|--------|
| **Status** | **PARTIALLY IMPLEMENTED** |
| **Relevant files** | `geometry/quantities.py`, `estimating/*`, `export_engine.py`, `EstimatePanel.jsx`, `IndiaBOQPanel.jsx` |
| **Functions** | Trade quantity rows; assemblies; India BOQ + GST; unit cost on conditions |
| **Quality** | Exportable quantities exist; estimating layer surprisingly deep for stage |
| **Technical debt** | Sample ratebook (not official DSR); waste/height assumptions |
| **Production needs** | Condition libraries per trade; validated formulas; estimating integrations |

---

## O. Scale detection

| Field | Detail |
|-------|--------|
| **Status** | **PARTIALLY IMPLEMENTED** |
| **Relevant files** | `ai/scale_detection.py`, `routes/scale_routes.py`, Takeoff calibrate UI |
| **Functions** | OCR suggest, graphic bar, two-point calibrate, accept suggestion |
| **Quality** | Manual calibrate works; OCR suggest unproven at scale |
| **Technical debt** | Fallback `9.0 px/ft` in spatial reasoning; default ratio 96 |
| **Production needs** | Mandatory scale confirmation before quantities marked trusted |

---

## P. Construction symbol recognition

| Field | Detail |
|-------|--------|
| **Status** | **BACKEND ONLY** / **EXPERIMENTAL** |
| **Relevant files** | `ai/detect_symbols.py`, `geometry/vector_symbol_match.py` |
| **Functions** | YOLO symbols (needs weights); geometric match heuristics |
| **Quality** | Not usable in product without weights; UI never calls `takeoffAPI.detectSymbols` |
| **Technical debt** | Two parallel approaches |
| **Production needs** | Fine-tuned symbol model + UI review loop |

---

## Q. AI image search

| Field | Detail |
|-------|--------|
| **Status** | **BACKEND ONLY** |
| **Relevant files** | `clip_embeddings.py`, `routes/ai_routes.py`, `services/api.js` (`searchAPI.image`) |
| **Functions** | CLIP embed + pgvector similarity |
| **Quality** | Code real; needs torch+CLIP + indexed tiles; **frontend never calls image search** |
| **Technical debt** | No bbox-draw → search UX (Togal’s signature flow) |
| **Production needs** | Tile indexing job + canvas bbox search UI |

---

## R. Text search

| Field | Detail |
|-------|--------|
| **Status** | **PARTIALLY IMPLEMENTED** |
| **Relevant files** | `ai_routes.py`, Takeoff search UI, PDF text via PyMuPDF words |
| **Functions** | `searchAPI.text` wired in Takeoff |
| **Quality** | Works when embeddings/text available; not proven across plan sets |
| **Technical debt** | Hybrid OCR+vector text incomplete |
| **Production needs** | Full-plan-set OCR index + highlight-on-sheet |

---

## S. Pattern search

| Field | Detail |
|-------|--------|
| **Status** | **MISSING** (count search is a weak proxy) |
| **Relevant files** | `searchAPI.count` only |
| **Quality** | No true visual pattern / template matching across sheets like Togal |
| **Production needs** | Patch-similarity or few-shot detector from user crop |

---

## T. Drawing comparison

| Field | Detail |
|-------|--------|
| **Status** | **IMPLEMENTED** (in-app) |
| **Relevant files** | `drawing_compare.py`, `routes/compare_routes.py`, `CompareModal` in `Takeoff.jsx` |
| **Functions** | ORB+RANSAC align, blue/red diff, optional sqft delta |
| **Quality** | Real CV compare; needs OpenCV in runtime image |
| **Technical debt** | Marketing `Comparison.jsx` is competitor marketing page, not this feature |
| **Production needs** | Quantify change by condition; side-by-side UX polish; OpenCV in API image or worker |

---

## U. Revision comparison

| Field | Detail |
|-------|--------|
| **Status** | **PARTIALLY IMPLEMENTED** |
| **Relevant files** | `compare_routes.py` revisions derived from shared `sheet_name` |
| **Functions** | `listRevisions`, compare pair |
| **Quality** | Heuristic revision grouping — not formal revision sets |
| **Technical debt** | No first-class `RevisionSet` model |
| **Production needs** | Explicit upload-as-revision workflow + change quantities |

---

## V. AI chat over plans

| Field | Detail |
|-------|--------|
| **Status** | **PARTIALLY IMPLEMENTED** |
| **Relevant files** | `routes/ai_routes.py` chat, Takeoff `ChatPanel`, `ChatWidget.jsx`, `mock/mockAI.js` |
| **Functions** | Anthropic Messages API with takeoff JSON context |
| **Quality** | Real when API key set; **not** visual/RAG over tiles; global ChatWidget is mock |
| **Technical debt** | Model id `"claude-sonnet-5"`; mock fallbacks; no citations to sheet regions |
| **Production needs** | Correct model; cite sheet+bbox; grounded answers only |

---

## W. Document/specification analysis

| Field | Detail |
|-------|--------|
| **Status** | **MISSING** |
| **Notes** | No specs ingestion, clause extraction, or cross-reference to drawings |

---

## X. RFI/proposal assistance

| Field | Detail |
|-------|--------|
| **Status** | **UI ONLY** / **PARTIAL** via chat prompt only |
| **Notes** | Chat system prompt can help draft text; no RFI object, workflow, or export templates |

---

## Y. Collaboration

| Field | Detail |
|-------|--------|
| **Status** | **PARTIALLY IMPLEMENTED** |
| **Relevant files** | `realtime.py`, `realtime_routes.py`, `sharing.py`, `ShareModal.jsx`, `Comment` model |
| **Functions** | WS presence/cursors; comments; guest share links |
| **Quality** | Better than placeholder; not Liveblocks CRDT co-editing of geometries |
| **Technical debt** | `SharedView` lists sheets only — guests cannot takeoff |
| **Production needs** | Shared canvas editing; conflict resolution; email invites |

---

## Z. Project management

| Field | Detail |
|-------|--------|
| **Status** | **PARTIALLY IMPLEMENTED** |
| **Relevant files** | `Dashboard.jsx`, `project_routes.py`, `CreateProjectModal.jsx` |
| **Quality** | Create/list/open projects works |
| **Technical debt** | Dashboard stats/activity **hardcoded mocks**; no project update/delete in UI; Settings = `#` |
| **Production needs** | Real activity log UI; project archive; search |

---

## AA. User/team management

| Field | Detail |
|-------|--------|
| **Status** | **PARTIALLY IMPLEMENTED** |
| **Relevant files** | `Team.jsx`, `team_routes.py`, `auth_routes.py`, `Invite` model |
| **Quality** | Roles + invite tokens work; **signup page broken**; no invite email |
| **Production needs** | Fix signup; email invites; org admin UX |

---

## AB. Permissions

| Field | Detail |
|-------|--------|
| **Status** | **IMPLEMENTED** (app-level RBAC) |
| **Relevant files** | `permissions.py`, role ranks, share permission levels |
| **Quality** | OWNER/ADMIN/MEMBER/VIEWER + share viewer/commenter |
| **Technical debt** | No fine-grained sheet/condition ACLs; integration tokens stored plaintext |
| **Production needs** | Audit every mutate route; encrypt secrets |

---

## AC. Data export

| Field | Detail |
|-------|--------|
| **Status** | **IMPLEMENTED** |
| **Relevant files** | `export_engine.py`, `routes/export_routes.py`, `estimating/estimate_export.py`, Takeoff export menu |
| **Functions** | Excel, CSV, PDF; India BOQ export; handoff CSV formats |
| **Quality** | Real file generation via openpyxl/reportlab |
| **Technical debt** | Quantities panel “Excel” button has no onClick (header export works) |
| **Production needs** | Mapping templates for DESTINI/Ediphi/Procore depth |

---

## AD. Integrations

| Field | Detail |
|-------|--------|
| **Status** | **PARTIALLY IMPLEMENTED** |
| **Relevant files** | `integrations/*`, `handoff_engine.py`, `integrations_routes.py` |
| **Functions** | File handoff CSV; Procore OAuth gated on env |
| **Quality** | Export-oriented; live OAuth incomplete |
| **Technical debt** | Tokens in plaintext Text columns |
| **Production needs** | Real OAuth + bidirectional sync or proven one-way handoff |

---

## AE. Billing/subscriptions

| Field | Detail |
|-------|--------|
| **Status** | **PARTIALLY IMPLEMENTED** |
| **Relevant files** | `stripe_routes.py`, `entitlements.py`, Pricing page |
| **Quality** | Checkout + webhook + usage caps exist |
| **Technical debt** | `mode="payment"` one-time, not Stripe Subscriptions |
| **Production needs** | Recurring subscriptions, customer portal, dunning |

---

## AF. Analytics

| Field | Detail |
|-------|--------|
| **Status** | **MISSING** / **UI ONLY** |
| **Notes** | Dashboard fake stats; Sentry optional; no product analytics (PostHog/etc.) |

---

## AG. Security

| Field | Detail |
|-------|--------|
| **Status** | **PARTIALLY IMPLEMENTED** |
| **Relevant files** | `auth.py` (JWT secret required in prod), `ratelimit.py`, CORS env |
| **Quality** | Basic auth hygiene improving; SSO ACS stub; plaintext integration tokens |
| **Technical debt** | Default DB password in docs; signup bypass risk via localStorage confusion |
| **Production needs** | Sec review, secret encryption, SSO completion, CSP, pen test |

---

## AH. Performance

| Field | Detail |
|-------|--------|
| **Status** | **PARTIALLY IMPLEMENTED** |
| **Relevant files** | OpenSeadragon tiling, inference tiling (`ai/inference/tiling.py`), Celery |
| **Quality** | Right ideas for large drawings |
| **Technical debt** | Render free tier; Redis not in blueprint; GPU not deployed |
| **Production needs** | Worker autoscaling, CDN for tiles, GPU queue SLAs |

---

## AI. Scalability

| Field | Detail |
|-------|--------|
| **Status** | **PARTIALLY IMPLEMENTED** (architecture sketch) / **MISSING** (ops) |
| **Notes** | Multi-tenant orgId present; no proven multi-region, no model A/B serving farm, Celery/Redis optional |

---

## Feature matrix (compact)

| ID | Feature | Status |
|----|---------|--------|
| A | Drawing ingestion | IMPLEMENTED |
| B | PDF/image processing | PARTIALLY IMPLEMENTED |
| C | OCR | PARTIALLY IMPLEMENTED |
| D | Sheet classification | PARTIALLY IMPLEMENTED |
| E | Auto naming | PARTIALLY IMPLEMENTED |
| F | Drawing organization | PARTIALLY IMPLEMENTED |
| G | Object detection | BACKEND ONLY (no weights) |
| H | AI takeoff | PARTIAL (vector only) |
| I | Manual takeoff | MISSING |
| J | Measurement | PARTIALLY IMPLEMENTED |
| K | Counting | PARTIALLY IMPLEMENTED |
| L | Area calculations | IMPLEMENTED (vector) |
| M | Linear measurements | PARTIALLY IMPLEMENTED |
| N | Quantity calculations | PARTIALLY IMPLEMENTED |
| O | Scale detection | PARTIALLY IMPLEMENTED |
| P | Symbol recognition | BACKEND ONLY |
| Q | AI image search | BACKEND ONLY |
| R | Text search | PARTIALLY IMPLEMENTED |
| S | Pattern search | MISSING |
| T | Drawing comparison | IMPLEMENTED |
| U | Revision comparison | PARTIALLY IMPLEMENTED |
| V | AI chat over plans | PARTIALLY IMPLEMENTED |
| W | Spec analysis | MISSING |
| X | RFI/proposal assist | MISSING / UI ONLY |
| Y | Collaboration | PARTIALLY IMPLEMENTED |
| Z | Project management | PARTIALLY IMPLEMENTED |
| AA | User/team management | PARTIALLY IMPLEMENTED |
| AB | Permissions | IMPLEMENTED |
| AC | Data export | IMPLEMENTED |
| AD | Integrations | PARTIALLY IMPLEMENTED |
| AE | Billing | PARTIALLY IMPLEMENTED |
| AF | Analytics | MISSING |
| AG | Security | PARTIALLY IMPLEMENTED |
| AH | Performance | PARTIALLY IMPLEMENTED |
| AI | Scalability | PARTIALLY IMPLEMENTED |

---

## Bottom line

TakeOff has a **credible SaaS + vector-geometry takeoff shell** with many Togal-adjacent features scaffolded. It does **not** yet have Togal’s product core: **reliable AI detection on real construction drawings + professional manual correction tools**. Until weights exist and manual takeoff works on real sheets, parity with Togal remains in the low twenties percent for the estimator’s critical path.
