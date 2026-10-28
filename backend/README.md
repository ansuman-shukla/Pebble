# Pebble backend

FastAPI + SQLModel + Alembic + Postgres, managed with uv (Python 3.12). Design: `../docs/design/08-architecture.md`.

```sh
make sync        # install dependencies into .venv (uv cache stays in ../.runtime)
make dev         # start Postgres (:5544) and the API on http://localhost:8100
make pre-commit  # lint (ruff, mypy strict) + tests; run before every commit
```

- Settings come from the repo-root `.env` (see `.env.example`); every value has a local default.
- New dependencies resolve only to versions published at least 7 days ago (`exclude-newer` in `pyproject.toml`).
- `make migrate` applies the Alembic migrations; `uv run python -m app.world.generate` (via the Makefile's uv env)
  generates the world from `data/world/world.yaml`, stores it and prints its stats. `GET /api/v1/world` also
  generates it on first request.
- Tests never touch the dev database: `tests/conftest.py` points the whole pytest process at `pebble_test` (same
  Postgres), creates it if missing, migrates it to head and empties its tables once per run. Use `db_session` for DB
  tests (one transaction, rolled back after the test; pass it to the app with `app.dependency_overrides[get_session]`).
  Tests that must really commit (e.g. LISTEN/NOTIFY) use `committing_engine`, which empties every table afterwards.
- `make export-openapi` writes `../frontend/openapi.json`; the frontend generates its client from it.
- `scripts/` holds the isolated launchers (`ds.sh`, `claude.sh`) and one-time `setup.sh`; they never touch the main
  devin-switch or global Devin/Claude config.
