from fastapi.testclient import TestClient
from sqlmodel import create_engine

from app.api.deps import get_engine
from app.core.config import settings
from app.main import app

HEALTH_URL = f"{settings.API_V1_STR}/health"


def test_health_reports_database_up(client: TestClient) -> None:
    response = client.get(HEALTH_URL)

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "up"}


def test_health_reports_database_down_when_unreachable(client: TestClient) -> None:
    unreachable = create_engine(
        "postgresql+psycopg://pebble:pebble@127.0.0.1:1/pebble", connect_args={"connect_timeout": 1}
    )
    app.dependency_overrides[get_engine] = lambda: unreachable

    response = client.get(HEALTH_URL)

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "down"}


def test_health_allows_the_frontend_origin(client: TestClient) -> None:
    origin = settings.FRONTEND_ORIGINS[0]

    response = client.get(HEALTH_URL, headers={"Origin": origin})

    assert response.headers["access-control-allow-origin"] == origin
