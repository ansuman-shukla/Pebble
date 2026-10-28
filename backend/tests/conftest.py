from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel

from app.core.db import engine
from app.db import models as _db_models  # noqa: F401  # registers every table on SQLModel.metadata
from app.main import app
from app.sim.navigation import Planner
from app.sim.simulation import Simulation
from app.sim.world import SimWorld
from tests.sim_helpers import real_world


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
        SQLModel.metadata.create_all(connection)  # every table in app.db.models, inside the rolled-back transaction
        with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
            yield session
        transaction.rollback()


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
