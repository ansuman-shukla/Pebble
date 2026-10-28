"""The game clock as spectators see it, and clock changes queued for the engine."""

from datetime import UTC, datetime, timedelta

from pydantic import BaseModel
from sqlmodel import Session

from app.db.models import Run
from app.db.schemas import ClockChange
from app.observability.store import latest_run, queue_command
from app.sim.clock import game_minute, town_clock

ENGINE_ALIVE_WITHIN = timedelta(seconds=5)


class ClockView(BaseModel):
    run_id: str
    status: str  # running | stopped
    engine_alive: bool  # the engine wrote a heartbeat in the last few seconds
    tick: int
    game_time: int  # town time in game minutes since day 0 00:00
    day: int
    time: str  # town time "HH:MM"
    speed: int  # ticks (game minutes) per real second
    paused: bool


class ClockCommandAccepted(BaseModel):
    command_id: int
    run_id: str


def run_or_latest(session: Session, run_id: str | None) -> Run | None:
    return session.get(Run, run_id) if run_id is not None else latest_run(session)


def read_clock(session: Session, run_id: str | None = None, now: datetime | None = None) -> ClockView | None:
    run = run_or_latest(session, run_id)
    if run is None:
        return None
    now = now or datetime.now(UTC)
    day, time = town_clock(run.tick)
    alive = run.status == "running" and run.updated_at is not None and now - run.updated_at <= ENGINE_ALIVE_WITHIN
    return ClockView(
        run_id=run.id,
        status=run.status,
        engine_alive=alive,
        tick=run.tick,
        game_time=game_minute(run.tick),
        day=day,
        time=time,
        speed=run.speed,
        paused=run.paused,
    )


def request_clock_change(
    session: Session, change: ClockChange, run_id: str | None = None
) -> ClockCommandAccepted | None:
    """Queue the change for the engine (it applies it within a tick or a quarter second when paused)."""
    run = run_or_latest(session, run_id)
    if run is None:
        return None
    command = queue_command(session, run.id, "clock", change.model_dump(exclude_none=True))
    session.commit()
    if command.id is None:
        raise RuntimeError("the database gave the command no id")
    return ClockCommandAccepted(command_id=command.id, run_id=run.id)
