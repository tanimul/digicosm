# ─── DCE Platform — Developer Makefile ────────────────────────────────────────
# Usage:  make up | make logs | make migrate | make shell | make seed

COMPOSE = docker compose -f docker/docker-compose.yml
BACKEND = $(COMPOSE) exec backend

.PHONY: up down restart logs shell migrate makemigrations seed test lint \
        frontend-install frontend-dev build-images ps

# ─── Services ─────────────────────────────────────────────────────────────────

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

restart:
	$(COMPOSE) restart

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f

logs-backend:
	$(COMPOSE) logs -f backend

logs-worker:
	$(COMPOSE) logs -f celery_worker

# ─── Database ─────────────────────────────────────────────────────────────────

makemigrations:
	$(BACKEND) python manage.py makemigrations

migrate:
	$(BACKEND) python manage.py migrate

migrations: makemigrations migrate

shell:
	$(BACKEND) python manage.py shell

dbshell:
	$(BACKEND) python manage.py dbshell

seed:
	$(BACKEND) python scripts/seed_data.py

superuser:
	$(BACKEND) python manage.py createsuperuser

# ─── Code quality ─────────────────────────────────────────────────────────────

test:
	$(BACKEND) pytest -v

lint-backend:
	$(BACKEND) ruff check .

lint-frontend:
	docker compose -f docker/docker-compose.yml exec frontend npm run lint

# ─── Frontend ─────────────────────────────────────────────────────────────────

frontend-install:
	cd frontend && npm install

frontend-dev:
	cd frontend && npm run dev

frontend-build:
	cd frontend && npm run build

# ─── Build ────────────────────────────────────────────────────────────────────

build-images:
	$(COMPOSE) build

# ─── Quick start (first time setup) ──────────────────────────────────────────

setup: up
	@echo "Waiting 10s for services to start..."
	@sleep 10
	$(MAKE) migrations
	$(MAKE) seed
	@echo ""
	@echo "DCE Platform is running!"
	@echo "  Backend API:  http://localhost:8000/api/v1/"
	@echo "  Frontend:     http://localhost:3000"
	@echo "  Django Admin: http://localhost:8000/admin/"
