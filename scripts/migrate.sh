#!/bin/bash
# ─── DCE Database Migration Script ──────────────────────────────────────────
# Run from repo root:  bash scripts/migrate.sh
# Or inside container: bash scripts/migrate.sh --seed

set -euo pipefail

SEED=false
if [[ "${1:-}" == "--seed" ]]; then
    SEED=true
fi

echo "==> Running migrations ..."
python backend/manage.py migrate --noinput

echo "==> Creating migration files for any unmigrated changes ..."
python backend/manage.py makemigrations --check --dry-run 2>/dev/null || \
    python backend/manage.py makemigrations

if [[ "$SEED" == "true" ]]; then
    echo "==> Seeding initial data ..."
    python scripts/seed_data.py
fi

echo "==> Done."
