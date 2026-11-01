"""Where everyone (citizens and animals) is and what they're doing, and which fires burn, now or at any past tick
(nearest snapshot + events)."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel
from sqlmodel import Session

from app.db.models import Run
from app.observability.events import AnimalGait, RoutePoint, Target
from app.observability.replay import ReplayAnimal, ReplayCitizen, ReplayEvent, ReplayFire, ReplayState, replay
from app.observability.store import events_after, latest_snapshot
from app.services.clock import run_or_latest
from app.sim.bodies import body_words
from app.sim.clock import SECONDS_PER_TICK, town_clock
from app.sim.fauna import AnimalKind
from app.sim.motion import Motion, Posture, body_motion, load_share
from app.sim.snapshot import SimSnapshot
from app.sim.state import AnimalActivity, Body, FireKind, Region, age_group
from app.sim.vec import Vec3, lat_lon_deg
from app.world_api.models import Driver

Activity = Literal[
    "idle",
    "walking",
    "running",
    "sleeping",
    "resting",
    "gathering",
    "eating",
    "drinking",
    "working",
    "hunting",
    "fishing",
    "tending_fire",
    "talking",
    "dead",
]
ACTIVITIES: dict[str, Activity] = {
    "walk_to": "walking",
    "follow": "walking",
    "flee": "running",
    "hunt": "hunting",
    "attack": "hunting",
    "fish": "fishing",
    "make_fire": "tending_fire",
    "feed_fire": "tending_fire",
    "sleep": "sleeping",
    "rest": "resting",
    "gather": "gathering",
    "eat": "eating",
    "drink": "drinking",
    "work": "working",
}
TALKING_TICKS = 3  # someone who just spoke (and isn't busy with something else) shows as talking this long


class TickNotReached(ValueError):
    pass


class Position(BaseModel):
    unit: Vec3  # direction from the planet's centre
    height_m: float  # ground height above sea level
    lat: float
    lon: float


class Needs(BaseModel):
    """0-100: hunger and thirst grow, energy and health run down."""

    hunger: float
    thirst: float
    energy: float
    health: float


class CitizenEntity(BaseModel):
    id: str
    name: str
    look: str
    appearance: str
    role: str
    region: Region
    position: Position
    heading_deg: float  # facing: yaw in the local tangent frame, 0 = south (+z local), 90 = east, 180 = north
    # how to draw their last tick's move: from where they stood when it began (the first point, t_s 0) through
    # `position` and on along their plan for ~2 game minutes, along walkable ground; draw them t_s game seconds into
    # the tick at each point (game seconds pass at the clock's speed), so the next tick's route starts where this
    # one's step ended
    route: list[RoutePoint]  # empty when they didn't move
    speed_mps: float  # ground speed where the route starts, game metres per game second (0 when they didn't move)
    activity: Activity  # what spectators see them doing (derived from the action, sleep, speech and death)
    cell: int
    alive: bool
    asleep: bool
    action: str | None  # e.g. walk_to, gather, sleep
    action_label: str  # destination or thing, in words
    state: list[str]  # coarse body words ("hungry", "tired"); empty = fine
    cause_of_death: str | None
    # spectator fields (10-world-v1 §6.4): how the body is drawn (the client maps motion and posture to clips and
    # poses, `sim/motion.py`), why and on what they act, their needs, purse and standing
    motion: Motion
    posture: Posture
    slot_heading: float | None  # facing on a seat, mat or work slot (yaw like heading_deg); None: their own heading
    slot_height_m: float | None  # how high the seat they sit on is (posture sitting); None: not on a seat
    goal: str  # what they are after, in their words (their latest set_goal); "" when unsaid
    driver: Driver | None  # why: hunger, thirst, rest, danger, duty, ambition, social, night
    target: Target | None  # what their action is about
    needs: Needs
    carrying: dict[str, int]  # item -> count (coins apart)
    coins: int
    rank: int | None  # 1 child .. 5 lord (10 §3.2); None: no member of society
    standing: int | None  # -100..100 with their own group; None: no member of society
    titles: list[str]  # lord, samurai, ashigaru, leader


class AnimalEntity(BaseModel):
    id: str
    kind: AnimalKind  # the spectator registry's kind (frontend `ANIMALS`)
    group: str  # herd, pack or shoal
    position: Position  # height_m: the ground, or the water surface for swimmers
    heading_deg: float  # yaw in the local tangent frame like citizens' (0 = south, 90 = east, 180 = north)
    activity: AnimalActivity
    # how to draw its last tick's move, the same rule as a citizen's route (empty when it didn't move)
    route: list[RoutePoint]
    speed_mps: float
    gait: AnimalGait
    goal: str  # what it is after, in words ("grazing", "stalking the deer"); "" when not told
    target: Target | None  # its quarry, its threat or where it heads


class FireEntity(BaseModel):
    id: str
    kind: FireKind  # a camp's fire pit, a town fire basket, or a campfire made anywhere
    position: Position
    lit: bool
    strength: float  # 0 out, 1/3 embers, 2/3 burning low, 1 burning


class EntitiesView(BaseModel):
    run_id: str
    tick: int
    day: int
    time: str
    tick_elapsed_s: float  # game seconds of the latest tick passed (tick_elapsed); 0 for a past tick (`at`)
    citizens: list[CitizenEntity]
    animals: list[AnimalEntity]
    fires: list[FireEntity]


def activity(citizen: ReplayCitizen, tick: int) -> Activity:
    if not citizen.alive:
        return "dead"
    doing = ACTIVITIES.get(citizen.action or "")
    if doing is not None:
        return doing
    if talking(citizen, tick):
        return "talking"
    return "idle"


def talking(citizen: ReplayCitizen, tick: int) -> bool:
    return citizen.said_tick is not None and tick - citizen.said_tick < TALKING_TICKS


def citizen_entity(citizen: ReplayCitizen, tick: int) -> CitizenEntity:
    hunger, thirst, energy, health = citizen.body
    lat, lon = lat_lon_deg(citizen.position)
    body = body_motion(
        alive=citizen.alive,
        asleep=citizen.asleep,
        action=citizen.action,
        args=citizen.action_args,
        gait=citizen.gait,
        load=load_share(citizen.inventory, age_group(citizen.age)),
        talking=talking(citizen, tick),
    )
    return CitizenEntity(
        id=citizen.id,
        name=citizen.name,
        look=citizen.look,
        appearance=citizen.appearance,
        role=citizen.role,
        region=citizen.region,
        position=Position(unit=citizen.position, height_m=citizen.height_m, lat=lat, lon=lon),
        heading_deg=citizen.heading_deg,
        route=list(citizen.route),
        speed_mps=citizen.speed_mps,
        activity=activity(citizen, tick),
        cell=citizen.cell,
        alive=citizen.alive,
        asleep=citizen.asleep,
        action=citizen.action,
        action_label=citizen.action_label,
        state=body_words(Body(hunger=hunger, thirst=thirst, energy=energy, health=health)) if citizen.alive else [],
        cause_of_death=citizen.cause_of_death,
        motion=body.motion,
        posture=body.posture,
        slot_heading=body.slot_heading,
        slot_height_m=body.slot_height_m,
        goal=citizen.goal,
        driver=citizen.driver,
        target=citizen.target,
        needs=Needs(hunger=hunger, thirst=thirst, energy=energy, health=health),
        carrying={item: count for item, count in citizen.inventory.items() if item != "coins"},
        coins=citizen.inventory.get("coins", 0),
        rank=citizen.member.rank if citizen.member is not None else None,
        standing=citizen.standing.get(citizen.region),
        titles=list(citizen.member.titles) if citizen.member is not None else [],
    )


def position(unit: Vec3, height_m: float) -> Position:
    lat, lon = lat_lon_deg(unit)
    return Position(unit=unit, height_m=height_m, lat=lat, lon=lon)


def animal_entity(animal: ReplayAnimal) -> AnimalEntity:
    return AnimalEntity(
        id=animal.id,
        kind=animal.kind,  # a species name: pydantic checks it is an AnimalKind
        group=animal.group,
        position=position(animal.position, animal.height_m),
        heading_deg=animal.heading_deg,
        activity=animal.activity,
        route=list(animal.route),
        speed_mps=animal.speed_mps,
        gait=animal.gait,
        goal=animal.goal,
        target=animal.target,
    )


def fire_entity(fire: ReplayFire) -> FireEntity:
    return FireEntity(
        id=fire.id,
        kind=fire.kind,
        position=position(fire.position, fire.height_m),
        lit=fire.lit,
        strength=fire.strength,
    )


def wild_entities(state: ReplayState) -> tuple[list[AnimalEntity], list[FireEntity]]:
    """Every animal (living, and remains until they're replaced) and every fire, by id."""
    animals = [animal_entity(animal) for _, animal in sorted(state.animals.items())]
    fires = [fire_entity(fire) for _, fire in sorted(state.fires.items())]
    return animals, fires


def tick_elapsed(counted_s: float, counted_at: datetime, speed: float, paused: bool, now: datetime) -> float:
    """Game seconds since the current tick happened, 0..SECONDS_PER_TICK: `counted_s` of them counted up to
    `counted_at` (the engine's write time of the tick: 0), the rest passing at the clock's speed while it runs. A page
    opened mid-tick draws walkers that far along the tick's path (D100: they trail the sim by one tick)."""
    passed = counted_s if paused else counted_s + (now - counted_at).total_seconds() * speed
    return min(max(passed, 0.0), float(SECONDS_PER_TICK))


def snapshot_before(tick: int) -> int:
    """The snapshot to replay a tick from: one before it, so the tick's own summary (walks ahead) is replayed too."""
    return max(tick - 1, 0)


@dataclass(frozen=True)
class WorldAt:
    run: Run
    tick: int
    state: ReplayState
    tick_written_at: datetime | None  # when the engine wrote the tick's summary (None: tick 0, or not replayed)
    snapshot: SimSnapshot  # the one the replay started from


def world_at(session: Session, run_id: str | None = None, at: int | None = None) -> WorldAt | None:
    """The replayed world of a run (the latest by default) now or at a past tick: the snapshot before it plus the
    events after it. None when there is no run; raises TickNotReached for a tick the run hasn't simulated yet."""
    run = run_or_latest(session, run_id)
    if run is None:
        return None
    tick = run.tick if at is None else at
    if tick > run.tick:
        raise TickNotReached(f"tick {tick} hasn't happened yet (the run is at {run.tick})")
    snapshot_row = latest_snapshot(session, run.id, at_or_before=snapshot_before(tick))
    if snapshot_row is None:
        raise TickNotReached(f"run {run.id} has no snapshot at or before tick {tick}")
    rows = events_after(session, run.id, snapshot_row.last_seq, until_tick=tick)
    events = [ReplayEvent(tick=e.tick, type=e.type, actor_id=e.actor_id, payload=e.payload) for e in rows]
    written = next((e.real_time for e in reversed(rows) if e.type == "tick_summary" and e.tick == tick), None)
    snapshot = SimSnapshot.model_validate(snapshot_row.state)
    return WorldAt(run=run, tick=tick, state=replay(snapshot, events), tick_written_at=written, snapshot=snapshot)


def entities_at(
    session: Session, run_id: str | None = None, at: int | None = None, now: datetime | None = None
) -> EntitiesView | None:
    """None when there is no run; raises TickNotReached for a tick the run hasn't simulated yet."""
    world = world_at(session, run_id, at)
    if world is None:
        return None
    day, time = town_clock(world.tick)
    elapsed = 0.0
    if at is None and world.tick_written_at is not None:
        run = world.run
        elapsed = tick_elapsed(0.0, world.tick_written_at, float(run.speed), run.paused, now or datetime.now(UTC))
    citizens = [citizen_entity(citizen, world.tick) for _, citizen in sorted(world.state.citizens.items())]
    animals, fires = wild_entities(world.state)
    return EntitiesView(
        run_id=world.run.id,
        tick=world.tick,
        day=day,
        time=time,
        tick_elapsed_s=elapsed,
        citizens=citizens,
        animals=animals,
        fires=fires,
    )
