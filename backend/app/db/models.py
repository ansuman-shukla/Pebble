"""Database tables."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, LargeBinary, UniqueConstraint, func
from sqlmodel import Field, SQLModel


class World(SQLModel, table=True):
    """A generated world: the served WorldView JSON, one row per (seed, generator version, spec hash)."""

    __tablename__ = "worlds"
    __table_args__ = (UniqueConstraint("seed", "generator_version", "spec_hash"),)

    id: int | None = Field(default=None, primary_key=True)
    seed: int = Field(sa_type=BigInteger)
    generator_version: str = Field(max_length=32)
    spec_hash: str = Field(max_length=64)
    payload: bytes = Field(sa_type=LargeBinary)  # WorldView as UTF-8 JSON, served as is
    created_at: datetime | None = Field(  # None until the database fills it in
        default=None, nullable=False, sa_type=DateTime(timezone=True), sa_column_kwargs={"server_default": func.now()}
    )
