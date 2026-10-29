"""Shared fixtures. The test process uses its own database (`pebble_test[_<worktree>]`), never the dev `pebble`."""

import os

from tests.database_name import BASE, suite_database_name

# before app.core.config builds settings, so every engine points here
os.environ["POSTGRES_DB"] = suite_database_name(override=os.environ.get("PEBBLE_TEST_DB"))

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, make_url, text
from sqlmodel import Session, SQLModel, create_engine

from app.core.config import settings
from app.core.db import engine
from app.db import models as _db_models  # noqa: F401  # registers every table on SQLModel.metadata
from app.main import app
from app.sim.navigation import Planner
from app.sim.simulation import Simulation
from app.sim.world import SimWorld
from tests.sim_helpers import real_world

TEST_DATABASE = os.environ["POSTGRES_DB"]
MIGRATIONS = Path(__file__).resolve().parents[1] / "app" / "alembic"
SETUP_LOCK = 20261028  # advisory lock id: concurrent test runs (other worktrees) set the database up one at a time


def _require_test_database(database: str | None) -> None:
    if database != TEST_DATABASE or not database.startswith(BASE):
        raise RuntimeError(f"refusing to truncate {database!r}: only the suite's database {TEST_DATABASE!r}")


def truncate_all(db_engine: Engine) -> None:
    """Empty every app table (the schema and Alembic's version stay); refuses any database but the suite's own."""
    _require_test_database(db_engine.url.database)
    tables = ", ".join(f'"{table.name}"' for table in SQLModel.metadata.sorted_tables)
    with db_engine.begin() as connection:
        _require_test_database(connection.execute(text("SELECT current_database()")).scalar_one())
        connection.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


def _migrate() -> None:
    config = Config()  # no ini file, so env.py leaves pytest's logging alone
    config.set_main_option("script_location", str(MIGRATIONS))
    command.upgrade(config, "head")


@pytest.fixture(scope="session", autouse=True)
def test_database() -> None:
    """Once per run: create the test database if missing, migrate it to head and empty its tables."""
    server_url = make_url(str(settings.SQLALCHEMY_DATABASE_URI)).set(database="postgres")
    server = create_engine(server_url, isolation_level="AUTOCOMMIT")
    with server.connect() as connection:
        connection.execute(text("SELECT pg_advisory_lock(:id)"), {"id": SETUP_LOCK})
        exists = connection.execute(text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": TEST_DATABASE})
        if exists.first() is None:
            connection.execute(text(f'CREATE DATABASE "{TEST_DATABASE}"'))
        _migrate()
        truncate_all(engine)
        connection.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": SETUP_LOCK})
    server.dispose()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def db_session() -> Iterator[Session]:
    """A session inside a transaction that is rolled back afterwards; its commits only release savepoints."""
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
            yield session
        transaction.rollback()


@pytest.fixture
def committing_engine() -> Iterator[Engine]:
    """The app's engine for tests that must really commit (NOTIFY only fires on commit); tables are emptied after."""
    yield engine
    truncate_all(engine)


# --- simulation: the real generated world (in memory, ~1 s once) and its planner ---


@pytest.fixture(scope="session")
def sim_world() -> SimWorld:
    return real_world()


@pytest.fixture(scope="session")
def planner(sim_world: SimWorld) -> Planner:
    return Planner(sim_world)


@pytest.fixture
def new_sim(sim_world: SimWorld, planner: Planner) -> Callable[..., Simulation]:
    def build(seed: int | None = None) -> Simulation:
        return Simulation.new(sim_world, seed=seed, planner=planner)

    return build
