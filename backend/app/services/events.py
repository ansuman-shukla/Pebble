"""Reading the event store with filters (spectators are omniscient: private events are included)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel
from sqlmodel import Session, col, select

from app.db.models import Event
from app.observability.events import ActorKind, EventType, Visibility
from app.services.clock import run_or_latest

MAX_LIMIT = 1000


class EventView(BaseModel):
    id: str
    seq: int
    run_id: str
    world_seed: int
    tick: int
    game_time: int
    real_time: datetime
    actor_kind: ActorKind
    actor_id: str | None
    type: EventType
    cell: int | None
    position: list[float] | None
    visibility: Visibility
    cause_id: str | None
    mind: dict[str, Any] | None
    payload: dict[str, Any]  # typed per event type: app.observability.events.PAYLOAD_TYPES


class EventsPage(BaseModel):
    run_id: str
    events: list[EventView]


def list_events(
    session: Session,
    *,
    run_id: str | None = None,
    actor: str | None = None,
    types: list[EventType] | None = None,
    since_tick: int | None = None,
    until_tick: int | None = None,
    after_seq: int | None = None,
    limit: int = 100,
) -> EventsPage | None:
    run = run_or_latest(session, run_id)
    if run is None:
        return None
    statement = select(Event).where(Event.run_id == run.id)
    if actor is not None:
        statement = statement.where(Event.actor_id == actor)
    if types:
        statement = statement.where(col(Event.type).in_(types))
    if since_tick is not None:
        statement = statement.where(Event.tick >= since_tick)
    if until_tick is not None:
        statement = statement.where(Event.tick <= until_tick)
    if after_seq is not None:
        statement = statement.where(Event.seq > after_seq)
    rows = session.exec(statement.order_by(col(Event.seq)).limit(min(limit, MAX_LIMIT))).all()
    return EventsPage(run_id=run.id, events=[EventView.model_validate(row, from_attributes=True) for row in rows])
