# TakeOff vs Togal.ai — Feature-Parity Re-Audit & Build Plan

**Date:** 2026-06-26
**Method:** Live audit of the `/home/user/TakeOff` codebase + multi-source web research of Togal.ai (official help.togal.ai docs, togal.ai marketing, third-party reviews/benchmarks, integration-partner announcements). Supersedes `TOGAL_GAP_ANALYSIS.md`.

---

## 0. TL;DR

- **What Togal really is:** a **takeoff / quantity** tool (AI auto-measures spaces, lines, counts on architectural floor plans), **not a full estimating platform**. Pricing/estimating happens in partner tools or exported spreadsheets.
- **What TakeOff is today:** a polished UI shell + a real-but-unfed AI detection backend. The core loop *(upload real plan → AI measures the actual drawing → user edits → trustworthy exportable quantities)* **does not work end-to-end**. Frontend runs on mock data over a hardcoded SVG; key backend endpoints (chat, search) are orphaned; no manual tools, no editing, no CorrectionEvent, no collaboration.
- **Good news:** parity is **smaller than it looks** — no estimating engine required, and Togal's own AI only outputs *geometry + counts that the user then classifies*. The differentiator to clone is the **detect → classify → correct loop**, not a giant semantic model.

---

## 1. Togal.ai — verified capabilities (the bar to match)

### 1.1 Core AI takeoff — the "Togal Button" (AUTODETECT)
One click runs automated takeoff on a sheet (~10–15 s/sheet). Per Togal's own help docs it outputs:
- **Footprint** (gross SF of the floor), **Gross area** (incl. walls), **Net area** (excl. walls) per room.
- **Wall center-lines + perimeter** as linear feet.
- **Counts** of ~18 pre-defined objects (doors, plumbing fixtures, appliances, furniture).

**Crucial nuance:** it does **not** semantically name each wall/door. It produces geometry; the estimator **box-selects → right-click → "auto classify"** into space types and assigns them to **conditions** (e.g., LVT flooring, drywall). Everything is editable. **"Re-Togaling"** re-runs the button while preserving prior reclassifications.

Three AI primitives, mapping 1:1 to our `Measurement` units: **Area (sqft, AIA standards) · Linear (ft) · Count**. Scope = architectural floor plans + reflected ceiling plans; **NOT** earthwork/cut-fill, structural volumes, or heavy civil.

### 1.2 AI Search (three modes, each → a classification)
- **Image Search** — box a symbol → find/count all matches across the set; auto-detects associated text to filter; saves search history.
- **Text Search** — type a phrase → find/count text matches; click to deselect false positives.
- **Pattern Search (beta)** — box a hatch/pattern → generates **area polygons** matching it; one drawing at a time.

### 1.3 Togal.CHAT
Right-side AI assistant that reads the **text** of uploaded plans/specs and answers conversationally, scoped to project / set / single drawing. Does **RFP/RFI/scope-of-work generation** and returns **page citations**. **Hard limit:** it cannot measure — takeoff stays with the dedicated tools.

### 1.4 Manual takeoff & edit suite
Count / linear / area / polygon, plus named editing tools: **Split, Cut, Merge, Arc/Curve, Smart Fill, Smart Copy/Paste, snapping (22.5/45/90°, edge/point/distance), rotation, markup, area breakdown.** Everything AI produces is human-editable.

### 1.5 Drawing comparison / revisions
**Compare** mode overlays two sheets: differences render **blue/red**, common geometry **grey**; auto-align + manual align; toggle sets with `T`. **Quantify changes in one click** ("Drawing Revision Management") — used for change orders.

### 1.6 Plan-set management
Upload PDF/JPEG/PNG/TIFF (+ hand-drawn). Handles **hundreds of sheets**; **auto-naming** organizes the set from sheet titles (OCR). **No DWG/CAD** support (an opportunity gap).

### 1.7 Notable 2025 launches
- **Repeating Groups** — take off one master unit (hotel room/apartment) → apply to hundreds of identical spaces.
- **Custom Formulas** — formula fields inside a classification (e.g., Total = Area × Unit Cost). *Lightweight pricing, not a cost database.*
- **Interactive 3D Takeoff**, advanced **Snapping UI**, **Rotation**, performance rewrite, **Assemblies Templates** (drywall/ceilings/framing; concrete planned 2026).

### 1.8 Exports & integrations
- **Export:** Excel + PDF, with **filtering, 3-level grouping, drawing-selection, an export multiplier (per floor/building), and an inline editable grid.** (CSV is not emphasized.)
- **Integrations (thin, partner-specific):** Procore, Bluebeam, Beck **DESTINI Estimator**, **Ediphi** (UPC/WBS mapping + audit trail — the integration gold standard), eTakeoff/OST, Zebel, ServiceTitan. **No public API.**
- **Estimating:** none built-in — no CSI cost database, no assembly pricing, no bid management. Quantities hand off to estimating partners.

### 1.9 Company context
SOC 2 Type II (2025); 3M+ plans analyzed; ARR up >1,000% (2024–25); pricing opaque (demo-gated), reviewer-reported ~$199–500/user/mo.

### 1.10 Real-world performance (independent reviews — important)
- "98% accuracy" is **vendor marketing**. Independent field reports: **~85% on clean residential floors, ~60% on complex/retail-podium levels**; University of Kansas peer-reviewed study found **~76% faster** than On-Screen Takeoff (a *speed*, not accuracy, validation).
- **Degrades on:** low-res/scanned/hand-drawn plans, complex MEP, complex wall intersections, missing labels, civil/structural.
- **Strong fit:** multifamily, retail/office TI, schools — clean 2D architectural PDFs.

---

## 2. TakeOff — current-state audit (ground truth)

| Area | Status | Evidence |
|---|---|---|
| Auth / signup / orgs | 🟢 Real | `auth.py`, `auth_routes.py`, `AuthContext.jsx` (JWT, org-scoped) |
| Projects CRUD | 🟢 Real | `project_routes.py`, `models.py` |
| Upload (PDF/PNG/JPG/TIFF) | 🟠 Partial | `upload_routes.py` real; local disk only (no S3); single-page processed |
| PDF/image viewer | 🟠 Partial | `DrawingRenderer.jsx` (react-pdf); **no tiling** (OOM risk on big sheets) |
| Scale detection | 🟠 Partial | `scale_detection.py` OCR works; **no manual two-point UI**; scale effectively hardcoded |
| AI room/space detection | 🔴 Non-functional | `detection_engine.py` (YOLOv8-seg) real, but **no weights** → empty; UI uses **mock on hardcoded SVG** |
| Measurement engine | 🟢 Real (unused) | `preprocessing.py` px→sqft/ft conversions exist |
| Symbol detection (doors/windows/MEP) | 🟠 Code-only | 27 classes defined; needs weights |
| Wall/linear | 🟠 Fake | heuristic `4·√area·1.8`, not vectorized (`spatial_reasoning.py`) |
| Manual takeoff/edit tools | 🔴 Absent | "Accept/Edit" buttons are dead; no canvas-draw library installed |
| Conditions/quantities | 🟠 Display-only | `QuantitiesPanel` reads detection JSON; no edit/persist; no `Condition` entity |
| Export | 🟠 Partial | `export_routes.py` Excel+CSV; **no PDF, no grouping/filter/multiplier/grid**; project export = first drawing only |
| Togal.CHAT | 🟠 Built-but-unwired | real Claude endpoint in `ai_routes.py` **not mounted**; UI calls mock `askTakeoffChat` |
| AI Search | 🔴 Stub | CLIP endpoint orphaned, returns `[]`, "TODO pgvector"; no UI |
| Drawing compare | 🔴 Absent | fake Rev A/B/C buttons; no backend/diff |
| Real-time collaboration | 🔴 Absent | no WebSocket; avatars hardcoded |
| Teams/roles/RBAC | 🟠 Partial | Org exists; no roles, no invites |
| Billing | 🟠 Partial | Stripe checkout only; no metering/entitlements |
| CorrectionEvent flywheel | 🔴 Absent | no table, no endpoint — corrections discarded |
| Data model | 🔴 JSON blobs | detections stored as JSON `Text`, **not PostGIS**; no pgvector |
| Async queue | 🟠 Partial | Celery/Redis configured; sync fallback; no webhook |
| Route wiring | 🔴 Issue | `ai_routes.py` (chat + search) **not mounted** in `server.py` |

**Parity score:** ~1/20 at parity, ~8 partial, ~11 missing/non-functional.

---

## 3. What to build to equal Togal (grouped & explained)

### 🔴 PHASE A — Make one takeoff real (the blocker; nothing sells before this)
1. **AI Area/Line/Count geometry on the actual drawing.** Train/fine-tune YOLOv8-seg on public floor-plan datasets (CubiCasa5K, RPLAN, Structured3D) → publish weights to S3. Render detections as an **overlay on `DrawingRenderer`** with one transform chain (image-px ↔ canvas ↔ PDF-pt ↔ feet). Delete the hardcoded `CanvasFull` SVG; replace `mockAI.js` with the real analyze+poll endpoints.
2. **Scale calibration UI** (manual two-point + OCR suggestion), persisted per `Sheet`. Every measurement depends on this.
3. **Auto-classify + manual edit suite** — box-select → assign to condition; tools: count/linear/area/polygon + **Split/Cut/Merge/Arc/Smart-fill**, snapping, rotation (Konva/Fabric). Match Togal's editing model.
4. **`Detection` + `CorrectionEvent` tables + HITL editing** — persist accept/reject/relabel/resize and log every correction (action, before, after, userId). *The flywheel; cheap now, irreplaceable later.*

### 🟠 PHASE B — The "Togal feel"
5. **Conditions/assemblies model** — named item (trade, unit, color, formula, waste%); both AI + manual measurements attach; editable live totals that persist. Add **Custom Formula** fields (Area × Unit Cost).
6. **Wire Togal.CHAT** — mount `ai_routes.py`, point `ChatPanel` at it, RAG context = detections + OCR + quantities; add RFP/RFI/scope templates + page citations. *Cheapest high-value win — mostly already written.*
7. **AI Search (image/text/pattern)** — enable pgvector, build CLIP patch embeddings on ingest, implement similarity query + OCR full-text + pattern→area-polygon; search UI; results convert to count/area classifications.
8. **Drawing compare** — overlay two sheets, **blue/red diff over grey**, auto+manual align, single-click change quantification. Hang on the existing Revisions sidebar.

### 🟢 PHASE C — Accuracy & scale (to rival real performance)
9. **Vector-PDF geometry engine** (PyMuPDF/pdfplumber) — measure true geometry on vector PDFs; biggest accuracy lever; absent today.
10. **True wall vectorization** — line-segment detection instead of the perimeter guess.
11. **Tiled big-sheet rendering** (OpenSeadragon/Pixi pyramid).
12. **Cloud storage (S3/R2) + signed URLs.**
13. **Plan-set ingestion + auto-naming** — split multi-page PDFs into sheets, OCR title block to name/number/organize (today only page 0 is processed).

### 🔵 PHASE D — SaaS-equal
14. **Rich export** — Excel + **PDF**, with grouping (3 levels), filtering, drawing selection, export multiplier, inline editable grid.
15. **One estimating-handoff integration** (Procore/DESTINI/Ediphi-style: quantities → UPC/WBS map + audit trail). *Not* an estimating engine.
16. **Real-time collaboration** (Liveblocks/Yjs presence, cursors, comments).
17. **Teams/roles/RBAC + invites.**
18. **Billing → entitlements + usage metering.**
19. **Repeating Groups** (master-unit → many) and **Interactive 3D** (demo value).

---

## 4. Differentiation openings (where Togal is weak)
- **Handle messy/complex drawings** (bad scans, MEP, complex walls) better than Togal's 60–85%.
- **Transparent measurement-error reporting** (confidence + error bars per quantity) — reviewers distrust the opaque 98% claim.
- **The CorrectionEvent flywheel** as a visible, compounding accuracy story.
- **Stronger, broader integrations + a public API** (Togal's are thin and a common complaint).
- **DWG/CAD ingestion** (Togal doesn't support it).
- **Transparent pricing** (Togal is demo-gated/opaque).

---

## 5. Realistic benchmark targets (for the eval harness)
Don't chase "98%". Gate model promotion on the defensible independent figures: **~70–76% time savings** and **within ~5% quantity margin** vs a manual baseline on a golden plan set, tracked per release (mIoU rooms, mAP symbols, measurement-error %).

---

### Sources
Official: help.togal.ai (how-to-use-togal-automated-takeoff, togal-chat, ai-image-search, text-search, pattern-search, how-to-compare-drawings, export tool, re-togaling, integrations), togal.ai (/features, /pricing-licenses, /vs/planswift, /vs/bluebeam, /blog/2025-features-roundup).
Integrations: ediphi.com (native integration, May 2026), beck-technology.com (DESTINI), Procore Marketplace.
Third-party: bidicontracting.com (2026 field review), roboticsandautomationnews.com (6-tool benchmark), trustpilot.com, g2.com, capterra.com, softwareadvice.com, insights.velocityaipartners.co, University of Kansas peer-reviewed study (Togal-hosted).
Codebase: live audit of `/home/user/TakeOff` (this session).
