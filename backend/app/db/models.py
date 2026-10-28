"""Database tables."""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Index, LargeBinary, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
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


class Run(SQLModel, table=True):
    """One simulation run over one stored world; the engine keeps its clock fields current."""

    __tablename__ = "runs"

    id: str = Field(primary_key=True, max_length=26)  # ULID
    world_seed: int = Field(sa_type=BigInteger)
    generator_version: str = Field(max_length=32)
    spec_hash: str = Field(max_length=64)
    status: str = Field(max_length=16)  # running | stopped
    tick: int = Field(default=0, sa_type=BigInteger)
    speed: int = 1  # ticks per real second
    paused: bool = Field(default=False, sa_type=Boolean)
    created_at: datetime | None = Field(
        default=None, nullable=False, sa_type=DateTime(timezone=True), sa_column_kwargs={"server_default": func.now()}
    )
    updated_at: datetime | None = Field(  # the engine's heartbeat
        default=None, nullable=False, sa_type=DateTime(timezone=True), sa_column_kwargs={"server_default": func.now()}
    )


class Event(SQLModel, table=True):
    """The append-only event store (06-observability): every state change and every mind output."""

    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("run_id", "seq"),
        Index("ix_events_run_tick", "run_id", "tick"),
        Index("ix_events_run_actor_tick", "run_id", "actor_id", "tick"),
        Index("ix_events_run_type_tick", "run_id", "type", "tick"),
    )

    id: str = Field(primary_key=True, max_length=26)  # ULID
    run_id: str = Field(foreign_key="runs.id", max_length=26)
    seq: int = Field(sa_type=BigInteger)  # per-run order, assigned by the simulation
    world_seed: int = Field(sa_type=BigInteger)
    tick: int = Field(sa_type=BigInteger)
    game_time: int = Field(sa_type=BigInteger)  # town time in game minutes since day 0 00:00
    real_time: datetime = Field(sa_type=DateTime(timezone=True))
    actor_kind: str = Field(max_length=16)
    actor_id: str | None = Field(default=None, max_length=64)
    type: str = Field(max_length=32)
    cell: int | None = None
    position: list[float] | None = Field(default=None, sa_type=JSONB)  # unit vector
    visibility: str = Field(max_length=8)
    cause_id: str | None = Field(default=None, max_length=26)
    mind: dict[str, Any] | None = Field(default=None, sa_type=JSONB)
    payload: dict[str, Any] = Field(sa_type=JSONB)


class Snapshot(SQLModel, table=True):
    """Full simulation state every game hour (and on shutdown); runs resume from the latest one."""

    __tablename__ = "snapshots"
    __table_args__ = (UniqueConstraint("run_id", "tick"),)

    id: str = Field(primary_key=True, max_length=26)  # ULID
    run_id: str = Field(foreign_key="runs.id", max_length=26)
    tick: int = Field(sa_type=BigInteger)
    last_seq: int = Field(sa_type=BigInteger)  # events up to this seq are inside the snapshot
    state: dict[str, Any] = Field(sa_type=JSONB)  # app.sim.snapshot.SimSnapshot
    created_at: datetime | None = Field(
        default=None, nullable=False, sa_type=DateTime(timezone=True), sa_column_kwargs={"server_default": func.now()}
    )


class EngineCommand(SQLModel, table=True):
    """Admin requests for the engine (pause, speed); the api writes them, the engine applies and stamps them."""

    __tablename__ = "engine_commands"

    id: int | None = Field(default=None, primary_key=True)
    run_id: str = Field(foreign_key="runs.id", max_length=26, index=True)
    kind: str = Field(max_length=32)
    payload: dict[str, Any] = Field(sa_type=JSONB)
    created_at: datetime | None = Field(
        default=None, nullable=False, sa_type=DateTime(timezone=True), sa_column_kwargs={"server_default": func.now()}
    )
    applied_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
