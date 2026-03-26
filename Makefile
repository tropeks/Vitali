.PHONY: help up down build migrate migrate-tenant shell test lint fmt create-tenant logs ps

# Default target
help:
	@echo ""
	@echo "  Vitali — Makefile Commands"
	@echo "  ══════════════════════════"
	@echo "  make up              Start all services (dev mode)"
	@echo "  make down            Stop all services"
	@echo "  make build           Rebuild Docker images"
	@echo "  make migrate         Run Django migrations (shared schema)"
	@echo "  make migrate-tenant  Run migrations on all tenant schemas"
	@echo "  make shell           Open Django shell"
	@echo "  make bash            Open bash in django container"
	@echo "  make test            Run backend tests"
	@echo "  make lint            Run ruff linter"
	@echo "  make fmt             Run ruff formatter"
	@echo "  make create-tenant   Create a new tenant (interactive)"
	@echo "  make logs            Follow all service logs"
	@echo "  make ps              Show running containers"
	@echo ""

# ─── Docker ──────────────────────────────────────────────────────────────────

up:
	docker compose up -d
	@echo "Services started. Django: http://localhost:8000 | Frontend: http://localhost:3000"

down:
	docker compose down

build:
	docker compose build --no-cache

logs:
	docker compose logs -f

ps:
	docker compose ps

# ─── Django ──────────────────────────────────────────────────────────────────

migrate:
	docker compose exec django python manage.py migrate_schemas --shared
	@echo "Shared schema migrations complete."

migrate-tenant:
	docker compose exec django python manage.py migrate_schemas
	@echo "All tenant schema migrations complete."

makemigrations:
	docker compose exec django python manage.py makemigrations $(app)

shell:
	docker compose exec django python manage.py shell_plus

bash:
	docker compose exec django bash

collectstatic:
	docker compose exec django python manage.py collectstatic --noinput

# ─── Testing & Quality ───────────────────────────────────────────────────────

test:
	docker compose exec django pytest -v $(args)

test-cov:
	docker compose exec django pytest --cov=apps --cov-report=html -v
	@echo "Coverage report: backend/htmlcov/index.html"

lint:
	docker compose exec django ruff check apps/ vitali/

fmt:
	docker compose exec django ruff format apps/ vitali/

typecheck:
	docker compose exec django mypy apps/ vitali/ --ignore-missing-imports

# ─── Tenant Management ───────────────────────────────────────────────────────

create-tenant:
	@echo "Creating tenant..."
	docker compose exec django python manage.py shell -c "\
from apps.core.models import Tenant, Domain; \
import sys; \
name = input('Clinic name: '); \
slug = input('Slug (schema name): '); \
domain = input('Domain (e.g. clinica.localhost): '); \
t = Tenant(name=name, slug=slug, schema_name=slug); \
t.save(); \
Domain.objects.create(domain=domain, tenant=t, is_primary=True); \
print(f'Tenant {name} created with schema {slug}') \
"

superuser:
	docker compose exec django python manage.py createsuperuser

# ─── Local dev (without Docker) ──────────────────────────────────────────────

install-dev:
	cd backend && pip install -r requirements/development.txt

run-dev:
	cd backend && python manage.py runserver

run-worker:
	cd backend && celery -A vitali worker -l debug

run-beat:
	cd backend && celery -A vitali beat -l debug --scheduler django_celery_beat.schedulers:DatabaseScheduler
