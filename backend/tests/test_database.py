"""The suite's own database: never the dev one, migrated to head, and emptied by `truncate_all`."""

from typing import Any

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, event, text
from sqlmodel import Session, create_engine, func, select

from app.api.deps import get_engine
from app.core.config import Settings, settings
from app.core.db import engine
from app.db.models import World
from tests.conftest import MIGRATIONS, TEST_DATABASE, truncate_all

DEV_DATABASE = Settings.model_fields["POSTGRES_DB"].default
UNREACHABLE = {"POSTGRES_SERVER": "127.0.0.1", "POSTGRES_PORT": "1"}  # nothing listens there: no run can touch a DB


def _unreachable_engine(database: str) -> Engine:
    host, port = UNREACHABLE["POSTGRES_SERVER"], UNREACHABLE["POSTGRES_PORT"]
    return create_engine(f"postgresql+psycopg://pebble:pebble@{host}:{port}/{database}")


def test_the_suite_never_uses_the_dev_database() -> None:
    assert TEST_DATABASE.startswith("pebble_test")
    assert TEST_DATABASE != DEV_DATABASE
    assert settings.POSTGRES_DB == TEST_DATABASE
    assert get_engine().url.database == TEST_DATABASE
    with engine.connect() as connection:
        assert connection.execute(text("SELECT current_database()")).scalar_one() == TEST_DATABASE


def test_the_test_database_is_migrated_to_head(db_session: Session) -> None:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    head = ScriptDirectory.from_config(config).get_current_head()
    assert db_session.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == head


def test_truncate_all_empties_committed_rows(committing_engine: Engine) -> None:
    with Session(committing_engine) as session:
        session.add(World(seed=1, generator_version="truncate-test", spec_hash="0" * 64, payload=b"{}"))
        session.commit()
        assert session.exec(select(func.count()).select_from(World)).one() == 1

    truncate_all(committing_engine)

    with Session(committing_engine) as session:
        assert session.exec(select(func.count()).select_from(World)).one() == 0


@pytest.mark.parametrize("database", [DEV_DATABASE, "pebble_test_another_worktree"])
def test_truncate_all_refuses_other_databases_before_connecting(database: str) -> None:
    with pytest.raises(RuntimeError, match=f"refusing to truncate '{database}'"):
        truncate_all(_unreachable_engine(database))


def test_truncate_all_refuses_when_the_suite_database_lost_its_test_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tests.conftest.TEST_DATABASE", DEV_DATABASE)
    with pytest.raises(RuntimeError, match=f"refusing to truncate '{DEV_DATABASE}'"):
        truncate_all(_unreachable_engine(DEV_DATABASE))


def test_truncate_all_checks_the_database_it_is_really_connected_to() -> None:
    lying_engine = create_engine(engine.url)  # its URL names the suite's database...

    @event.listens_for(lying_engine, "do_connect")
    def _connect_elsewhere(dialect: Any, record: Any, cargs: Any, cparams: dict[str, Any]) -> None:  # noqa: ARG001  # SQLAlchemy's listener signature
        cparams["dbname"] = "postgres"  # ...but it lands on the server's maintenance database

    try:
        with pytest.raises(RuntimeError, match="refusing to truncate 'postgres'"):
            truncate_all(lying_engine)
    finally:
        lying_engine.dispose()
