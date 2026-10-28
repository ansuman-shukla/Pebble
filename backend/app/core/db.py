from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError
from sqlmodel import create_engine

from app.core.config import settings

engine = create_engine(str(settings.SQLALCHEMY_DATABASE_URI), pool_pre_ping=True, connect_args={"connect_timeout": 2})


def database_is_up(db_engine: Engine) -> bool:
    try:
        with db_engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except OperationalError:
        return False
    return True
