#!/bin/bash
# ─── DCE Backend Entrypoint ──────────────────────────────────────────────────
# Waits for Postgres and Redis to be ready, then runs Django setup and starts
# the application server.

set -euo pipefail

# ── Colour helpers ────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log()  { echo -e "${GREEN}[entrypoint]${NC} $*"; }
warn() { echo -e "${YELLOW}[entrypoint]${NC} $*"; }
die()  { echo -e "${RED}[entrypoint] ERROR:${NC} $*" >&2; exit 1; }

# ── Wait for a TCP service ────────────────────────────────────────────────────
wait_for() {
    local host=$1
    local port=$2
    local name=$3
    local retries=${4:-30}
    local wait=2

    log "Waiting for $name at $host:$port ..."
    for i in $(seq 1 "$retries"); do
        if nc -z "$host" "$port" 2>/dev/null; then
            log "$name is ready."
            return 0
        fi
        warn "  attempt $i/$retries — $name not ready, retrying in ${wait}s ..."
        sleep "$wait"
    done
    die "$name did not become ready after $((retries * wait))s."
}

# ── Parse DATABASE_URL for host/port ─────────────────────────────────────────
DB_HOST=$(echo "${DATABASE_URL:-}" | sed -E 's|.*@([^:/]+).*|\1|')
DB_PORT=$(echo "${DATABASE_URL:-}" | sed -E 's|.*:([0-9]+)/.*|\1|')
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"

REDIS_HOST=$(echo "${REDIS_URL:-}" | sed -E 's|redis://([^:/]+).*|\1|')
REDIS_PORT=$(echo "${REDIS_URL:-}" | sed -E 's|redis://[^:]+:([0-9]+).*|\1|')
REDIS_HOST="${REDIS_HOST:-localhost}"
REDIS_PORT="${REDIS_PORT:-6379}"

wait_for "$DB_HOST"    "$DB_PORT"    "PostgreSQL"
wait_for "$REDIS_HOST" "$REDIS_PORT" "Redis"

# ── Django setup ──────────────────────────────────────────────────────────────
log "Creating migration files ..."
python manage.py makemigrations --noinput

log "Running database migrations ..."
python manage.py migrate --noinput

log "Collecting static files ..."
python manage.py collectstatic --noinput --clear

# ── Start application ─────────────────────────────────────────────────────────
log "Starting application: $*"
exec "$@"
