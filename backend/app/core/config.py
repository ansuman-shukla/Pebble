from pathlib import Path

from pydantic import PostgresDsn, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]
WORLD_DATA_DIR = REPO_ROOT / "backend" / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", env_ignore_empty=True, extra="ignore")

    PROJECT_NAME: str = "Pebble"
    API_V1_STR: str = "/api/v1"
    FRONTEND_ORIGINS: list[str] = ["http://localhost:5180"]

    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5544
    POSTGRES_USER: str = "pebble"
    POSTGRES_PASSWORD: str = "pebble"
    POSTGRES_DB: str = "pebble"

    @computed_field  # type: ignore[prop-decorator]  # mypy can't type a decorated property; pydantic documents this
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> PostgresDsn:
        return PostgresDsn.build(
            scheme="postgresql+psycopg",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            host=self.POSTGRES_SERVER,
            port=self.POSTGRES_PORT,
            path=self.POSTGRES_DB,
        )


settings = Settings()
