"""Fixtures for the spectator endpoint tests: the api reads the test transaction, places come from the test world."""

from collections.abc import Iterator

import pytest
from sqlmodel import Session

from app.api.deps import get_place_index, get_session
from app.engine import EngineLoop
from app.main import app
from app.services.places import PlaceIndex
from app.sim.world import SimWorld
from tests.api.spectator import Story, live_cast, tell_story


@pytest.fixture
def spectator_session(db_session: Session, sim_world: SimWorld) -> Iterator[Session]:
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[get_place_index] = lambda: PlaceIndex(sim_world)
    yield db_session


@pytest.fixture
def story(spectator_session: Session, sim_world: SimWorld) -> Story:
    return tell_story(spectator_session, sim_world)


@pytest.fixture
def cast(spectator_session: Session, sim_world: SimWorld) -> EngineLoop:
    return live_cast(spectator_session, sim_world)
