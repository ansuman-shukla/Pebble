from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError
from sqlmodel import create_engine

from app.core.config import settings


def create_db_engine(application_name: str | None = None) -> Engine:
    """An engine on the app database; `application_name` labels its connections in `pg_stat_activity`."""
    connect_args: dict[str, object] = {"connect_timeout": 2}
    if application_name is not None:
        connect_args["application_name"] = application_name
    return create_engine(str(settings.SQLALCHEMY_DATABASE_URI), pool_pre_ping=True, connect_args=connect_args)


engine = create_db_engine()


def database_is_up(db_engine: Engine) -> bool:
    try:
        with db_engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except OperationalError:
        return False
    return True
