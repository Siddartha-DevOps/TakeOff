#!/usr/bin/env bash
# Backend container entrypoint: migrate → (optional) seed → serve.
set -e

echo "[start] alembic upgrade head"
alembic upgrade head

if [ "${SEED_ON_START:-false}" = "true" ]; then
  echo "[start] seeding demo data (SEED_ON_START=true)"
  # Non-fatal: a re-deploy over an already-seeded DB shouldn't crash the service.
  python seed.py || echo "[start] seed skipped/failed — continuing"
fi

PORT="${PORT:-8000}"
echo "[start] uvicorn on 0.0.0.0:${PORT}"
exec uvicorn server:app --host 0.0.0.0 --port "${PORT}"
