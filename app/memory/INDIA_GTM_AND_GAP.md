# TakeOff — India Go-To-Market & Gap Plan

**Date:** 2026-06-26
**Purpose:** What it takes for TakeOff to be a real **Togal.ai alternative in India** — the verified engineering gap, the India-specific localization the US-built Togal lacks, and the incremental build order. Companion to `TOGAL_PARITY_REAUDIT.md`.

---

## 1. Verified current state (ground truth, not commit messages)

**Real & wired end-to-end:** SaaS backbone (RBAC/teams, billing entitlements, real-time collab, repeating groups, rich export, handoff-as-file), **PostGIS** geometry + pgvector + clean Alembic chain, **vector-PDF measurement** on the actual drawing with correct coordinate transform + tiling, **CorrectionEvent flywheel**, and real CI (Postgres+PostGIS, migrations, 12 test files, e2e smoke test).

**Still fake / missing — the "AI like Togal" core:**
1. **No trained model, no weights, no dataset** anywhere. Detection falls back to hardcoded mock (raster) or empty (vector-CV). `/api/health` reports `mock_mode`.
2. **Raster/scanned-sheet detection doesn't work** — only *vector* PDFs get real measurements.
3. **CLIP AI-search inert** — real query code, but nothing is indexed (503) because the torch/CLIP stack isn't installed and weights are download-blocked.
4. **OCR unproven** — PaddleOCR/pytesseract not installed.
5. **Walls derived from room edges**, not detected from linework.
6. **Retraining flywheel is orchestration-only** — needs a GPU + dataset + golden set that don't exist.
7. **GPU inference host not wired**; heavy ML stack not installed in the running backend.

**Cheap bugs:** Togal.CHAT needs `ANTHROPIC_API_KEY` (503 without it). (Model id `claude-sonnet-5` is valid — verify, don't assume broken.)

**Net:** ~70% of a Togal *shell* with a real geometry engine; **0% of a working AI detector.** That gap closes only via *labeled data → trained weights → GPU host*, in that order.

---

## 2. Why a straight Togal clone fails in India

Togal is built for the US: **AIA measurement standards, USD, US drawing symbology**. India runs on a different standard, different rate books, different formats, different price points, and heavier AutoCAD use. These are **additional** requirements on top of Togal parity — and they are where Togal is weakest, so they are the moat.

| # | India requirement | Why mandatory | Togal? |
|---|---|---|---|
| 1 | **IS 1200 mode of measurement** (net quantities, opening deductions) | Legal/tender basis for all Indian measurement (CPWD/PWD/private) | ❌ AIA |
| 2 | **CPWD DSR + state PWD SOR rate DBs** (DSR 2023/2025) | Estimators price BOQs against active DSR/SOR | ❌ |
| 3 | **BOQ in Indian tender format** + rate analysis (labour+material+plant+overhead), chapter/abstract rollups | The BOQ *is* the deliverable in Indian pre-con | ❌ (quantities only) |
| 4 | **Metric-first units** (m³ concrete, m² plaster, running m) + sqft toggle | Indian structural work is metric | ❌ imperial |
| 5 | **GST (18%)**, overheads, contingencies | Every Indian quote needs it | ❌ |
| 6 | **DWG/AutoCAD input** | Heavier AutoCAD use in India; Togal lacks it | ❌ |
| 7 | **Indian symbology in training data** | US-trained weights underperform on local drawings | ❌ |
| 8 | **INR pricing ₹1,500–5,000/mo** | Togal's ~₹17–25k/user/mo is unsellable to Indian SMBs | ❌ |
| 9 | **DPDP Act 2023 + India data residency** | Data-localization expectation for enterprise/govt | ❌ |
| 10 | **Hindi / regional-language UI** | Widens SMB market (BuildNext markets "Hindi-friendly") | ❌ |
| 11 | **MEP quantity takeoff** | Large Indian QTO buyer segment | Partial |

## 3. India competitive field
BuildNext, RDash (Indian residential, ₹2–5k/mo) · RIB CostX (QS pro choice) · PlanSwift (~₹60–90k one-time) · STACK/Autodesk (₹2 lakh+/yr) · InfraLens/EstiMate/designdrafter (BOQ + CPWD-DSR + AI QTO, from ₹1,500/mo) · Togal (premium, US-centric = the opening).

## 4. Strategic reframe (founder)
- **Don't be "Togal for India" — be "AI takeoff + IS-1200 BOQ + DSR pricing," which Togal is NOT.** Togal stops at quantities and has no cost DB; in India the **DSR-priced BOQ is the product**. Beat Togal locally instead of copying it.
- **Train on Indian drawings** — off-distribution accuracy collapses (Togal itself drops to 60–85% off its sweet spot).
- **Price for India** (INR, per-project or low per-seat, GST-invoiced), **host in India** (DPDP).
- **Wedge:** QS consultants + SMB GCs doing repetitive residential/commercial — where AI takeoff works best and the DSR-BOQ layer is the hook Togal can't offer.

---

## 5. Build order (incremental; ✅ = shippable/testable now, 🖥️ = needs GPU/data)

**India estimating layer (the moat — pure code, testable now):**
1. ✅ **Metric units + IS 1200 measurement** (opening deductions, net quantities, volumes) — *increment #1, this PR.*
2. ✅ **DSR/SOR rate database + BOQ generation** (item → rate analysis: labour+material+plant+overhead; chapter/abstract rollups).
3. ✅ **GST (18%) + overheads/contingencies** + Indian tender abstract format.
4. ✅ Wire BOQ into conditions + rich export (Excel/PDF BOQ).

**AI core (critical path — scaffolded here, executed on a GPU box):**
5. 🖥️ **Labeled dataset** — annotate Indian drawings (CVAT/Roboflow) starting from CubiCasa5K/RPLAN.
6. 🖥️ **Train weights** — YOLOv8-seg (rooms) + symbol detector to the promotion gate (mIoU≥0.70).
7. 🖥️ **GPU inference host** (Modal/Replicate/RunPod) + weights in S3.
8. ✅/🖥️ **Zero-shot bootstrap (SAM2)** to demo detection before training completes.

**Fixes & fill-ins (mostly code, testable):**
9. ✅ Chat: require/validate `ANTHROPIC_API_KEY`; verify model id.
10. ✅ Metric/DWG ingestion path; raster detection once weights exist.
11. ✅ INR/GST billing; India hosting/DPDP posture.

---

## 6. One-line
The SaaS + geometry shell is built; the AI detector is not. In parallel with funding the *data→weights→GPU* critical path, build the **IS 1200 + DSR-BOQ + GST** layer that makes this a genuine **India** product Togal can't match — starting with metric/IS-1200 measurement.

### Sources
India standards/market: constructionestimatorindia.com (BOQ/DSR/IS-1200, AI takeoff, pricing), infralens.in/boq, designdrafter.com, constructionplacements.com (QS software). Togal: TOGAL_PARITY_REAUDIT.md. Codebase: live re-audit (this session).
