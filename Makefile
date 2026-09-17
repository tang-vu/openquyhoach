SHELL := /bin/bash
PY := .venv/bin/python
UV := .venv/bin/uv
export UV_PROJECT_ENVIRONMENT := .venv

.PHONY: help setup infra up down migrate seed dev api web worker test test-unit test-integration \
        lint lint-fix typecheck format format-check sources-validate openapi web-serve clean doctor

help: ## Show targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

setup: ## Install all dependencies (python + node)
	$(UV) sync --all-packages
	pnpm install

infra: ## Start PostGIS, MinIO, Redis
	docker compose up -d db minio minio-init redis

up: ## Start full local stack (db, minio, redis, api)
	docker compose up -d db minio minio-init redis api

down: ## Stop everything
	docker compose down

migrate: ## Run DB migrations
	$(PY) -m alembic -c db/alembic.ini upgrade head

seed: ## Seed synthetic DemoDistrict demo data
	$(PY) -m openquyhoach_cli.main db seed --demo

doctor: ## Check environment health
	$(PY) -m openquyhoach_cli.main doctor

dev: infra migrate seed ## infra + migrate + seed (then run `make api` and `make web`)

api: ## Run API locally (hot reload)
	$(PY) -m uvicorn openquyhoach_api.app:app --host 0.0.0.0 --port 8000 --reload --app-dir apps/api/src

worker: ## Run worker locally
	$(PY) -m openquyhoach_worker.main --app-dir apps/worker/src

web: ## Run web dev server
	pnpm --filter @openquyhoach/web dev

test: test-unit test-integration ## All tests

test-unit: ## Unit tests (no services needed)
	$(PY) -m pytest -m "not integration" -q

test-integration: ## Integration tests (needs `make infra`)
	$(PY) -m pytest -m integration -q

lint: ## Ruff + eslint
	$(UV) run ruff check python apps tests scripts
	pnpm -r lint --if-present

lint-fix:
	$(UV) run ruff check --fix python apps tests scripts
	pnpm -r lint --if-present -- --fix

format: ## Ruff format + prettier
	$(UV) run ruff format python apps tests scripts

format-check:
	$(UV) run ruff format --check python apps tests scripts

typecheck: ## mypy + tsc
	$(UV) run mypy python apps
	pnpm -r typecheck --if-present

sources-validate: ## Validate source descriptors
	$(PY) -m openquyhoach_cli.main sources validate

openapi: ## Export OpenAPI schema to docs/openapi.json
	$(PY) scripts/export_openapi.py

web-serve: ## Build web as static export and serve on :3100
	pnpm --filter @openquyhoach/web build
	python3 -m http.server 3100 -d apps/web/out

clean: ## Remove build artifacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	find . -name "*.egg-info" -type d -prune -exec rm -rf {} +
