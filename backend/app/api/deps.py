from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Engine
from sqlmodel import Session

from app.core.db import engine
from app.world.generate import GENERATOR
from app.world.store import WorldGenerator


def get_engine() -> Engine:
    return engine


EngineDep = Annotated[Engine, Depends(get_engine)]


def get_session(db_engine: EngineDep) -> Iterator[Session]:
    with Session(db_engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


def get_world_generator() -> WorldGenerator:
    return GENERATOR


WorldGeneratorDep = Annotated[WorldGenerator, Depends(get_world_generator)]
