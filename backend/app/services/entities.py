"""Where everyone is and what they're doing, now or at any past tick (nearest snapshot + events)."""

from pydantic import BaseModel
from sqlmodel import Session

from app.observability.replay import ReplayCitizen, ReplayEvent, replay
from app.observability.store import events_after, latest_snapshot
from app.services.clock import run_or_latest
from app.sim.bodies import body_words
from app.sim.clock import town_clock
from app.sim.snapshot import SimSnapshot
from app.sim.state import Body
from app.sim.vec import Vec3, lat_lon_deg


class TickNotReached(ValueError):
    pass


class Position(BaseModel):
    unit: Vec3  # direction from the planet's centre
    height_m: float  # ground height above sea level
    lat: float
    lon: float


class CitizenEntity(BaseModel):
    id: str
    name: str
    look: str
    appearance: str
    position: Position
    cell: int
    alive: bool
    asleep: bool
    action: str | None  # e.g. walk_to, gather, sleep
    action_label: str  # destination or thing, in words
    state: list[str]  # coarse body words ("hungry", "tired"); empty = fine
    cause_of_death: str | None


class EntitiesView(BaseModel):
    run_id: str
    tick: int
    day: int
    time: str
    citizens: list[CitizenEntity]


def _entity(citizen: ReplayCitizen) -> CitizenEntity:
    hunger, thirst, energy, health = citizen.body
    lat, lon = lat_lon_deg(citizen.position)
    return CitizenEntity(
        id=citizen.id,
        name=citizen.name,
        look=citizen.look,
        appearance=citizen.appearance,
        position=Position(unit=citizen.position, height_m=citizen.height_m, lat=lat, lon=lon),
        cell=citizen.cell,
        alive=citizen.alive,
        asleep=citizen.asleep,
        action=citizen.action,
        action_label=citizen.action_label,
        state=body_words(Body(hunger=hunger, thirst=thirst, energy=energy, health=health)) if citizen.alive else [],
        cause_of_death=citizen.cause_of_death,
    )


def entities_at(session: Session, run_id: str | None = None, at: int | None = None) -> EntitiesView | None:
    """None when there is no run; raises TickNotReached for a tick the run hasn't simulated yet."""
    run = run_or_latest(session, run_id)
    if run is None:
        return None
    tick = run.tick if at is None else at
    if tick > run.tick:
        raise TickNotReached(f"tick {tick} hasn't happened yet (the run is at {run.tick})")
    snapshot_row = latest_snapshot(session, run.id, at_or_before=tick)
    if snapshot_row is None:
        raise TickNotReached(f"run {run.id} has no snapshot at or before tick {tick}")
    events = [
        ReplayEvent(tick=e.tick, type=e.type, actor_id=e.actor_id, payload=e.payload)
        for e in events_after(session, run.id, snapshot_row.last_seq, until_tick=tick)
    ]
    state = replay(SimSnapshot.model_validate(snapshot_row.state), events)
    day, time = town_clock(tick)
    citizens = [_entity(citizen) for _, citizen in sorted(state.citizens.items())]
    return EntitiesView(run_id=run.id, tick=tick, day=day, time=time, citizens=citizens)
