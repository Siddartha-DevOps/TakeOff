#!/usr/bin/env bash
# Reproducible end-to-end verification against a REAL Postgres + PostGIS + pgvector.
#
# Stands up a local database, applies the full Alembic migration chain, runs the
# backend unit tests, then runs scripts/smoke_test.py (vector AUTODETECT ->
# PostGIS persistence -> ST_Area round-trip). This is the exact sequence that was
# verified by hand; CI (.github/workflows/ci.yml) runs the same steps.
#
# Usage:  bash app/backend/scripts/run_local_e2e.sh
set -euo pipefail

DB_USER="${DB_USER:-takeoff_user}"
DB_PASS="${DB_PASS:-takeoff_dev_pass_2025}"
DB_NAME="${DB_NAME:-takeoff_db}"
export DATABASE_URL="postgresql://${DB_USER}:${DB_PASS}@localhost/${DB_NAME}"

BACKEND_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$BACKEND_DIR"

echo "== install postgis + pgvector extensions (idempotent) =="
if ! ls /usr/lib/postgresql/16/lib/postgis-3.so >/dev/null 2>&1; then
  apt-get update -y && apt-get install -y --fix-missing postgresql-16-postgis-3 postgresql-16-pgvector
fi

echo "== start postgres cluster =="
pg_ctlcluster 16 main start 2>/dev/null || pg_ctlcluster 16 main restart

echo "== create role + database (idempotent) =="
sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'" | grep -q 1 || \
  sudo -u postgres psql -c "CREATE ROLE ${DB_USER} LOGIN PASSWORD '${DB_PASS}' SUPERUSER;"
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1 || \
  sudo -u postgres psql -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};"

echo "== install python deps (curated: engine + db + test) =="
python3 -m pip install -q \
  pymupdf shapely numpy pytest \
  sqlalchemy geoalchemy2 pgvector psycopg2-binary alembic python-dotenv loguru

echo "== alembic upgrade head (real PostGIS) =="
python3 -m alembic upgrade head

echo "== backend unit tests =="
python3 -m pytest tests/ -q

echo "== end-to-end smoke test (vector -> PostGIS -> ST_Area) =="
python3 scripts/smoke_test.py

echo "== ALL GREEN =="
