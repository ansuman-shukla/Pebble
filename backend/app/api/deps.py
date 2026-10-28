from typing import Annotated

from fastapi import Depends
from sqlalchemy import Engine

from app.core.db import engine


def get_engine() -> Engine:
    return engine


EngineDep = Annotated[Engine, Depends(get_engine)]
