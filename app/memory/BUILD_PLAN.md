# TakeOff — Build Plan to Togal Parity (A2 → D6)

Execution plan for the remaining parity items from `TOGAL_PARITY_REAUDIT.md`.
**Done so far:** #26 vector geometry, #27 PostGIS model, one-click AUTODETECT
(Area/Line/Count on the real plan), A1 symbol counts.

## How to build this (the rules)

1. **One item → one branch → one draft PR.** Never batch the whole roadmap into
   one session; context runs out and PRs become unreviewable. Only batch the
   items explicitly marked *(build together)*.
2. **Build in dependency order** (this file's order), not audit-number order.
3. **Every PR:** tests written and passing, type-check/lint clean, no AI
   inference inside a Vercel route (CLAUDE.md guardrail), env documented.
4. **State what you couldn't verify here.** The remote container has no GPU, no
   live PostGIS, no S3/Stripe/Liveblocks keys — for those, deliver code + tests
   + a documented run path, not a false "it works."

### Prompt template (paste one per session)

```
Implement <ITEM ID>: <name> from app/memory/BUILD_PLAN.md.
Branch: <branch from the item block>.
Follow the block's sub-tasks and acceptance criteria. Write tests, commit,
push, open a draft PR. Tell me what you could not verify in this environment.
```

---

## Phase A — make takeoff fully real & editable

### A6 — Persist geometry to PostGIS (BUILD FIRST) · `claude/takeoff-a6-persist-postgis`
- **Why first:** unblocks every feature that stores/queries geometry (A4, A5, B1, B4).
- **Do:** apply migrations `0001`+`0002` to the target DB; on AUTODETECT/detect_symbols,
  write a `Sheet` row and persist rooms/walls/symbols as `Detection` + `Measurement`
  rows (use `geometry.postgis` / `symbols_to_persistence`); read them back for results.
- **Done when:** a vector AUTODETECT populates `sheets`/`detections`/`measurements`;
  `/results` reads from PostGIS, not just the JSON blob; round-trip test passes.
- **Can't verify here:** needs a live PostGIS DB — provide a docker-compose/Neon note
  and a test using a Postgis test DB or SQLite-skip.

### A3 — Scale calibration UI · `claude/takeoff-a3-scale-calibration`
- **Do:** two-point calibration on the canvas (click a known dimension → enter feet)
  + OCR suggestion from `scale_detection`; persist `scale_ratio`/`scale_text` per
  `Sheet` (or `Drawing.scale`). Re-run AUTODETECT uses it.
- **Done when:** user sets scale manually, it persists, and measurements recompute.
- **Dep:** A6 (to persist on Sheet) — can fall back to `Drawing.scale` without it.

### A2 + A4 + A5 — Editable detect→classify→correct loop *(build together)* · `claude/takeoff-a2a4a5-edit-loop`
- **Why together:** one UX loop; A5 needs the edit/classify events A2/A4 emit. This is
  the actual product differentiator (per the reaudit), not a big model.
- **A2 Manual edit suite:** add Konva or Fabric overlay; draw/move/resize/delete
  count/line/area/polygon; Split/Cut/Merge/Arc/Smart-fill, snapping, rotation.
- **A4 Auto-classify:** box-select detections → assign space type / condition.
- **A5 CorrectionEvent capture:** POST endpoint writing `CorrectionEvent`
  (action, before, after, userId, detectionId) on every accept/reject/edit/relabel.
- **Done when:** every AI detection is editable, reclassifiable, and each change
  writes a `CorrectionEvent` row.
- **Dep:** A6.

---

## Phase B — the "Togal feel"

### B2 — Wire Togal.CHAT (cheapest win) · `claude/takeoff-b2-chat`
- **Do:** mount `routes/ai_routes.py` in `server.py`; point `ChatPanel` at the real
  `/drawings/{id}/chat` (drop the mock `askTakeoffChat`); RAG context = detections +
  OCR + quantities; add RFP/RFI/scope templates + page citations.
- **Done when:** chat answers from real detection data with citations; mock removed.
- **Dep:** none — code largely exists, just unmounted.

### B1 — Conditions / assemblies · `claude/takeoff-b1-conditions`
- **Do:** CRUD for `Condition` (trade, type, unit, color, formula, waste%); attach AI
  + manual measurements; live editable totals that persist; custom formula field
  (Area × unit cost).
- **Done when:** measurements roll up to conditions with live, persisted totals.
- **Dep:** A6.

### B4 — Drawing compare / revisions · `claude/takeoff-b4-compare`
- **Do:** overlay two sheets; diff render blue/red over grey; auto + manual align;
  one-click change quantification. Hang on the existing Revisions sidebar.
- **Done when:** two revisions overlay with a quantified delta.

### B3 — AI Search (image / text / pattern) · `claude/takeoff-b3-ai-search`
- **Do:** enable pgvector (extend migration); build CLIP patch embeddings on ingest;
  image similarity + OCR full-text + pattern→area-polygon; search UI; results become
  count/area conditions.
- **Done when:** box a symbol → find+count matches across the set.
- **Can't verify here:** needs pgvector DB + CLIP weights.

---

## Phase C — accuracy & scale

### C3 — Cloud storage (S3/R2) + signed URLs · `claude/takeoff-c3-object-storage`
- **Do:** presigned uploads to R2/S3; store URLs (not disk paths); update
  `upload_routes` + `DrawingRenderer` fetch. **Can't verify here:** needs bucket creds.

### C4 — Plan-set ingestion + auto-naming · `claude/takeoff-c4-plansets`
- **Do:** split multi-page PDFs into `Sheet` rows; OCR the title block to name/number
  and organize the set (today only page 0 is processed).

### C2 — Tiled big-sheet rendering · `claude/takeoff-c2-tiling`
- **Do:** OpenSeadragon/Pixi pyramid tiling to stop OOM on large sheets; overlay must
  track the tiled transform.

### C1 — True wall vectorization · `claude/takeoff-c1-walls`
- **Do:** detect/classify wall centerline segments (typed walls) instead of summing
  raw linework length. **Dep:** vector engine (done).

### C5 — Eval harness · `claude/takeoff-c5-eval`
- **Do:** mIoU (rooms) / mAP (symbols) / measurement-error % on a golden set; gate
  `ModelVersion.promoted`. Target ~70–76% time-savings & within ~5% quantity margin
  (not "98%"). **Can't verify here:** needs datasets/GPU.

---

## Phase D — SaaS parity

### D1 — Rich export · `claude/takeoff-d1-export`
- **Do:** add PDF export; 3-level grouping, filtering, drawing selection, export
  multiplier, inline editable grid. Fix project export (currently first drawing only).

### D2 — Estimating handoff integration · `claude/takeoff-d2-integration`
- **Do:** one partner-style export (Procore/DESTINI/Ediphi): quantities → UPC/WBS map
  + audit trail. *Not* an estimating engine.

### D4 — Teams / roles / RBAC + invites · `claude/takeoff-d4-rbac`
- **Do:** roles (owner/estimator/viewer), permission checks, org invites. **Dep:** auth (done).

### D5 — Billing → entitlements + metering · `claude/takeoff-d5-billing`
- **Do:** map Stripe subscription → feature entitlements + usage metering (sheets/AI
  runs). **Can't verify here:** needs Stripe keys/webhooks.

### D3 — Real-time collaboration · `claude/takeoff-d3-collab`
- **Do:** Liveblocks or Yjs presence, cursors, comments (replace hardcoded avatars).
  **Can't verify here:** needs Liveblocks keys.

### D6 — Repeating groups + interactive 3D · `claude/takeoff-d6-repeating-3d`
- **Do:** take off one master unit → apply to many identical spaces; simple 3D view.

---

## Cross-cutting cleanups (do opportunistically, not their own phase)
- Remove vestigial MongoDB in `server.py` (`motor`/`status_checks`) — the app is
  Postgres now.
- Finish the async path: real completion webhook instead of the sync fallback
  (Celery/Redis already configured).
- Train the raster YOLOv8-seg symbol/space weights off-box and publish to S3.
