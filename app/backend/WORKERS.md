# Durable processing workers

Production drawing analysis and Deep Zoom tile generation run only through
Celery. PostgreSQL `processing_jobs` rows are the durable source of truth;
Redis is the broker/result transport and is not the status database.

Required production services and variables:

- PostgreSQL/PostGIS via `DATABASE_URL`
- Redis via `REDIS_URL`
- one Celery worker: `celery -A celery_app worker --loglevel=INFO --concurrency=1 -B`
- Task 3 object storage: `REQUIRE_OBJECT_STORAGE=true`, `S3_BUCKET`, and the
  relevant AWS or S3-compatible endpoint credentials
- existing inference configuration: `AI_INFERENCE_SPACE_ID`,
  `AI_INFERENCE_API_NAME`, `AI_INFERENCE_TIMEOUT_SECONDS`, and `HF_TOKEN`

Optional worker tuning:

- `JOB_MAX_ATTEMPTS` (default `3`)
- `JOB_STALE_SECONDS` (default `900`)
- `JOB_SOFT_TIME_LIMIT` (default `900`)
- `JOB_HARD_TIME_LIMIT` (default `1200`)

The recovery beat republishes queued/retrying jobs and stale running jobs.
Production startup rejects a missing Redis URL, and `/api/readiness` separately
reports broker and live-worker availability. Local tests may set
`TAKEOFF_DISABLE_BACKGROUND_ANALYSIS=true` to isolate remote raster inference;
there is no production FastAPI/in-process execution fallback.
