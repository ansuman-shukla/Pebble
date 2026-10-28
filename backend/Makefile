.PHONY: help sync format lint test pre-commit dev engine db-up db-down migrate export-openapi

ROOT := $(abspath ..)
UV := env -u XDG_DATA_HOME -u XDG_CONFIG_HOME -u XDG_CACHE_HOME -u XDG_STATE_HOME \
	UV_CACHE_DIR=$(ROOT)/.runtime/uv-cache UV_PYTHON_INSTALL_DIR=$(ROOT)/.runtime/uv-python uv
COMPOSE := docker compose -f $(ROOT)/docker-compose.yml

help:
	@echo "sync            install dependencies (uv)"
	@echo "format          ruff format + autofix"
	@echo "lint            ruff check, ruff format --check, mypy"
	@echo "test            start Postgres and run pytest"
	@echo "pre-commit      lint + test (run before every commit)"
	@echo "dev             start Postgres, migrate, and run the API on :8100 with reload"
	@echo "engine          start Postgres, migrate, and run the simulation engine (ENGINE_ARGS=\"--speed 10\")"
	@echo "db-up / db-down start / stop local Postgres (:5544, data in .runtime/postgres)"
	@echo "migrate         alembic upgrade head"
	@echo "export-openapi  write ../frontend/openapi.json"

sync:
	$(UV) sync

format:
	$(UV) run ruff format
	$(UV) run ruff check --fix

lint:
	$(UV) run ruff check
	$(UV) run ruff format --check
	$(UV) run mypy app tests scripts/export_openapi.py

test: db-up
	$(UV) run pytest

pre-commit: lint test

dev: migrate
	$(UV) run uvicorn app.main:app --reload --port 8100

engine: migrate
	$(UV) run python -m app.engine $(ENGINE_ARGS)

db-up:
	$(COMPOSE) up -d --wait db

db-down:
	$(COMPOSE) stop db

migrate: db-up
	$(UV) run alembic upgrade head

export-openapi:
	$(UV) run python -m scripts.export_openapi ../frontend/openapi.json
