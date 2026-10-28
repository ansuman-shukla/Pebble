from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel

from app.core.db import engine
from app.db.models import World
from app.main import app


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
        SQLModel.metadata.create_all(connection, tables=[SQLModel.metadata.tables[World.__tablename__]])
        with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
            yield session
        transaction.rollback()
