"""The suite's own database: never the dev one, migrated to head, and emptied by `truncate_all`."""

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text
from sqlmodel import Session, func, select

from app.api.deps import get_engine
from app.core.config import Settings, settings
from app.core.db import engine
from app.db.models import World
from tests.conftest import MIGRATIONS, TEST_DATABASE, truncate_all

DEV_DATABASE = Settings.model_fields["POSTGRES_DB"].default


def test_the_suite_never_uses_the_dev_database() -> None:
    assert TEST_DATABASE == "pebble_test" != DEV_DATABASE
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
