# Production AI Search release runbook

## Required production configuration

- Render: `DATABASE_URL`, `JWT_SECRET_KEY`, explicit `CORS_ORIGINS`,
  `AI_INFERENCE_SPACE_ID`, `HF_TOKEN`.
- Durable uploads: `REQUIRE_OBJECT_STORAGE=true` plus `S3_BUCKET`, endpoint,
  access key, secret key, and region.
- GitHub Actions: repository secret `HF_TOKEN`, with write access to
  `Siddartha96/takeoff-spaces-inference`.
- Recommended: `SENTRY_DSN`, `INTEGRATION_ENCRYPTION_KEYS`, and
  `INTERNAL_WEBHOOK_SECRET`.

The API exposes `/api/health` for service health and strict `/api/readiness`
for the release dependencies. Neither endpoint returns secret values.

## Deployment order

1. Upload `app/backend/ai/space` to the private Hugging Face Space. Confirm
   `/embed_clip_text` returns a normalized 512-value vector.
2. Deploy the backend. `alembic upgrade head` applies revision
   `k9e0f1a2b3c4` before Uvicorn starts.
3. Confirm `/api/health` is 200 and `/api/readiness` reports
   `release_ready: true`.
4. Reindex each existing project once using
   `POST /api/takeoff/projects/{project_id}/search/reindex` as an authorized
   user. New analyses index CLIP regions and OCR automatically.
5. Verify text search, region search, find-all, grouped counts, and the review
   accept/reject gate on at least two sheets.

## Rollback

- Application rollback: redeploy the previous Render commit. Do not downgrade
  the database during an incident; the new columns/tables are additive and old
  application versions ignore them.
- Search rollback: redeploy the prior Hugging Face Space commit. Existing
  encoder-versioned embeddings remain isolated from incompatible encoders.
- Stop the release if migration fails, readiness is false, error rate rises,
  or a smoke test crosses organization/project boundaries.
