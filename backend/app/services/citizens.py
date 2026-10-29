"""Citizen pages for spectators: everyone at a glance, one citizen's profile, their life as a timeline of one-line
summaries, and their needs over time. Spectators are omniscient: private events (knowledge, needs) are included.
"""

import math
from collections.abc import Sequence
from functools import cache
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import and_, func, or_
from sqlmodel import Session, col, select

from app.db.models import Event
from app.observability.events import (
    WORLD_V1_TYPES,
    ActionEnded,
    ActionStarted,
    Died,
    EventType,
    Injured,
    ItemLocation,
    ItemMoved,
    KnowledgeChanged,
    NeedChanged,
    Perceived,
    Said,
    Visibility,
)
from app.observability.lines import Names, Resident, Told, namer, tell
from app.services.clock import run_or_latest
from app.services.entities import Activity, Position, citizen_entity, world_at
from app.services.places import PlaceIndex, PlaceRef
from app.sim.bodies import LEVEL_WORDS, NEEDS, Need, need_level
from app.sim.citizens import CITIZENS, DEV_CITIZENS, CitizenSpec, load_citizens
from app.sim.clock import town_clock
from app.sim.items import ITEMS, amount_words
from app.sim.state import Region

TIMELINE_TYPES: tuple[EventType, ...] = (
    "citizen_spawned",
    "action_started",
    "action_finished",
    "action_interrupted",
    "said",
    "need_changed",
    "injured",
    "died",
    "item_moved",
    "knowledge_changed",
    "intervention",
    *WORLD_V1_TYPES,
)  # `perceived` (every look around, long) only when asked for
RECENT_ENTRIES = 8
MAX_TIMELINE = 500
DEFAULT_NEEDS_SPAN = 24 * 60  # the last game day
MAX_NEED_POINTS = 1000
LONGEST_ACTION_TICKS = 24 * 60  # how far back an ended action's start is looked for (a long sleep is ~10 h)

Order = Literal["asc", "desc"]


class CitizenNotFound(LookupError):
    pass


class PersonRef(BaseModel):
    id: str
    name: str
    role: str


class CitizenSummary(BaseModel):
    id: str
    name: str
    look: str
    role: str
    region: Region
    age: int
    alive: bool
    activity: Activity
    action_label: str
    state: list[str]  # coarse body words ("hungry"); empty = fine
    place: PlaceRef | None  # the named place they are in, if any
    cause_of_death: str | None


class CitizensView(BaseModel):
    run_id: str
    tick: int
    day: int
    time: str
    citizens: list[CitizenSummary]


class NeedReading(BaseModel):
    need: Need
    value: float  # 0..100: hunger and thirst rise, energy and health fall
    word: str  # "fed", "hungry", "starving", …


class Holding(BaseModel):
    item: str
    count: int
    words: str  # "a handful of berries"


class KnownPlace(PlaceRef):
    level: str  # visited | rough (heard of it)


class TimelineEntry(BaseModel):
    id: str
    seq: int
    tick: int
    day: int
    time: str
    type: EventType
    visibility: Visibility
    summary: str  # one line, third person, without the citizen's name ("walks to the well")
    detail: str | None  # what the citizen was told or heard, in their own words
    related: list[str]  # other citizens in it (who heard them, who spoke)


class CitizenProfile(BaseModel):
    run_id: str
    tick: int
    day: int
    time: str
    id: str
    name: str
    look: str
    appearance: str
    age: int
    age_group: str
    sex: str | None
    role: str
    region: Region
    skills: list[str]
    personality: str
    home: PlaceRef | None
    alive: bool
    asleep: bool
    cause_of_death: str | None
    activity: Activity
    action: str | None
    action_label: str
    position: Position
    place: PlaceRef | None
    needs: list[NeedReading]
    state: list[str]
    inventory: list[Holding]
    known_places: list[KnownPlace]
    known_people: list[PersonRef]
    recent: list[TimelineEntry]  # newest first


class TimelinePage(BaseModel):
    run_id: str
    citizen_id: str
    entries: list[TimelineEntry]
    next_cursor: int | None  # pass as `cursor` for the next page (a seq); None = no more


class NeedPoint(BaseModel):
    tick: int
    hunger: float
    thirst: float
    energy: float
    health: float


class NeedsSeries(BaseModel):
    run_id: str
    citizen_id: str
    from_tick: int
    to_tick: int
    step: int  # ticks between points (raised so a series has at most MAX_NEED_POINTS)
    points: list[NeedPoint]


@cache
def _specs() -> dict[str, CitizenSpec]:
    return {spec.id: spec for path in (DEV_CITIZENS, CITIZENS) for spec in load_citizens(path).citizens}


def roster(session: Session, run_id: str) -> dict[str, PersonRef]:
    """Everyone who ever lived in the run, by id (from their `citizen_spawned` events)."""
    statement = select(Event.actor_id, Event.payload).where(Event.run_id == run_id, Event.type == "citizen_spawned")
    return {
        actor_id: PersonRef(id=actor_id, name=payload["name"], role=payload.get("role", ""))
        for actor_id, payload in session.exec(statement).all()
        if actor_id is not None
    }


def residents(session: Session, run_id: str) -> dict[str, Resident]:
    """Everyone who ever lived in the run with their home and age, by id (for naming households in lines)."""
    statement = select(Event.actor_id, Event.payload).where(Event.run_id == run_id, Event.type == "citizen_spawned")
    return {
        actor_id: Resident(payload["name"], payload.get("home"), payload["age"])
        for actor_id, payload in session.exec(statement).all()
        if actor_id is not None
    }


def list_citizens(
    session: Session, places: PlaceIndex, run_id: str | None = None, at: int | None = None
) -> CitizensView | None:
    world = world_at(session, run_id, at)
    if world is None:
        return None
    day, time = town_clock(world.tick)
    citizens = []
    for _, citizen in sorted(world.state.citizens.items()):
        entity = citizen_entity(citizen, world.tick)
        citizens.append(
            CitizenSummary(
                id=citizen.id,
                name=citizen.name,
                look=citizen.look,
                role=citizen.role,
                region=citizen.region,
                age=citizen.age,
                alive=citizen.alive,
                activity=entity.activity,
                action_label=entity.action_label,
                state=entity.state,
                place=places.where(citizen.position),
                cause_of_death=citizen.cause_of_death,
            )
        )
    return CitizensView(run_id=world.run.id, tick=world.tick, day=day, time=time, citizens=citizens)


def citizen_profile(
    session: Session, places: PlaceIndex, citizen_id: str, run_id: str | None = None, at: int | None = None
) -> CitizenProfile | None:
    """None when there is no run; raises CitizenNotFound and TickNotReached."""
    world = world_at(session, run_id, at)
    if world is None:
        return None
    citizen = world.state.citizens.get(citizen_id)
    if citizen is None:
        raise CitizenNotFound(f"no citizen {citizen_id} in run {world.run.id} at tick {world.tick}")
    entity = citizen_entity(citizen, world.tick)
    spec = _specs().get(citizen_id)
    people = roster(session, world.run.id)
    hunger, thirst, energy, health = citizen.body
    values: dict[Need, float] = {"hunger": hunger, "thirst": thirst, "energy": energy, "health": health}
    recent = citizen_timeline(
        session, places, citizen_id, run_id=world.run.id, to_tick=world.tick, limit=RECENT_ENTRIES, order="desc"
    )
    day, time = town_clock(world.tick)
    return CitizenProfile(
        run_id=world.run.id,
        tick=world.tick,
        day=day,
        time=time,
        id=citizen.id,
        name=citizen.name,
        look=citizen.look,
        appearance=citizen.appearance,
        age=citizen.age,
        age_group=citizen.group,
        sex=spec.sex if spec is not None else None,
        role=citizen.role,
        region=citizen.region,
        skills=list(citizen.skills),
        personality=spec.personality if spec is not None else "",
        home=PlaceRef(id=citizen.home, name=places.structure_name(citizen.home)) if citizen.home else None,
        alive=citizen.alive,
        asleep=citizen.asleep,
        cause_of_death=citizen.cause_of_death,
        activity=entity.activity,
        action=entity.action,
        action_label=entity.action_label,
        position=entity.position,
        place=places.where(citizen.position),
        needs=[
            NeedReading(need=need, value=values[need], word=LEVEL_WORDS[need][need_level(need, values[need])])
            for need in NEEDS
        ],
        state=entity.state,
        inventory=[
            Holding(item=item, count=count, words=amount_words(count, ITEMS[item]))
            for item, count in sorted(citizen.inventory.items())
        ],
        known_places=[
            KnownPlace(id=place_id, name=places.place_name(place_id), level=level)
            for place_id, level in sorted(citizen.places.items())
        ],
        known_people=[
            people.get(person_id, PersonRef(id=person_id, name=person_id, role=""))
            for person_id in sorted(citizen.people)
        ],
        recent=recent.entries if recent is not None else [],
    )


def citizen_timeline(
    session: Session,
    places: PlaceIndex,
    citizen_id: str,
    *,
    run_id: str | None = None,
    from_tick: int | None = None,
    to_tick: int | None = None,
    types: Sequence[EventType] | None = None,
    order: Order = "asc",
    cursor: int | None = None,
    limit: int = 100,
) -> TimelinePage | None:
    """The citizen's events (theirs, and speech they heard) as one-liners; page with `cursor`. None when there is no
    run; raises CitizenNotFound."""
    run = run_or_latest(session, run_id)
    if run is None:
        return None
    people = roster(session, run.id)
    if citizen_id not in people:
        raise CitizenNotFound(f"no citizen {citizen_id} in run {run.id}")
    wanted = list(types or TIMELINE_TYPES)
    mine = and_(col(Event.actor_id) == citizen_id, col(Event.type).in_(wanted))
    statement = select(Event).where(Event.run_id == run.id)
    if "said" in wanted:
        heard = and_(col(Event.type) == "said", col(Event.payload)["heard_by"].contains([citizen_id]))
        statement = statement.where(or_(mine, heard))
    else:
        statement = statement.where(mine)
    if from_tick is not None:
        statement = statement.where(Event.tick >= from_tick)
    if to_tick is not None:
        statement = statement.where(Event.tick <= to_tick)
    if cursor is not None:
        statement = statement.where(col(Event.seq) > cursor if order == "asc" else col(Event.seq) < cursor)
    seq = col(Event.seq)
    rows = session.exec(statement.order_by(seq if order == "asc" else seq.desc()).limit(limit)).all()
    labels = start_labels(session, run.id, citizen_id, rows)
    names = namer(residents(session, run.id))
    entries = [timeline_entry(row, citizen_id, people, places, labels, names) for row in rows]
    next_cursor = rows[-1].seq if len(rows) == limit else None
    return TimelinePage(run_id=run.id, citizen_id=citizen_id, entries=entries, next_cursor=next_cursor)


def citizen_needs(
    session: Session,
    citizen_id: str,
    *,
    run_id: str | None = None,
    from_tick: int | None = None,
    to_tick: int | None = None,
    step: int | None = None,
) -> NeedsSeries | None:
    """Hunger, thirst, energy and health every `step` ticks from the tick summaries (the last game day by default).
    None when there is no run; raises CitizenNotFound."""
    run = run_or_latest(session, run_id)
    if run is None:
        return None
    if citizen_id not in roster(session, run.id):
        raise CitizenNotFound(f"no citizen {citizen_id} in run {run.id}")
    end = min(run.tick if to_tick is None else to_tick, run.tick)
    start = max(0, end - DEFAULT_NEEDS_SPAN) if from_tick is None else min(from_tick, end)
    span = end - start
    step = max(step or math.ceil(span / 288) or 1, math.ceil(span / MAX_NEED_POINTS), 1)
    body = col(Event.payload)["bodies"][citizen_id]
    statement = (
        select(Event.tick, body)
        .where(
            Event.run_id == run.id,
            Event.type == "tick_summary",
            Event.tick >= start,
            Event.tick <= end,
            func.mod(col(Event.tick) - start, step) == 0,
        )
        .order_by(col(Event.tick))
    )
    points = [
        NeedPoint(tick=tick, hunger=values[0], thirst=values[1], energy=values[2], health=values[3])
        for tick, values in session.exec(statement).all()
        if values is not None  # not alive (yet, or any more)
    ]
    return NeedsSeries(run_id=run.id, citizen_id=citizen_id, from_tick=start, to_tick=end, step=step, points=points)


# --- one-line summaries ---

_GERUNDS = {
    "walk_to": "walking",
    "follow": "following",
    "flee": "fleeing",
    "gather": "gathering",
    "eat": "eating",
    "drink": "drinking",
    "sleep": "sleeping",
    "rest": "resting",
    "wait": "waiting",
    "work": "working",
}


def _started(started: ActionStarted) -> str:
    label = started.label
    match started.action:
        case "walk_to":
            if label == "your home":
                return "walks home"
            return f"walks {label}" if label.startswith("to ") else f"walks to {label or 'somewhere'}"
        case "follow":
            return f"follows {label}"
        case "flee":
            return f"flees {label}".rstrip()
        case "gather":
            return f"gathers {label}"
        case "eat":
            return f"eats {label}"
        case "drink":
            return f"drinks at {label}" if label else "drinks"
        case "sleep":
            return "lies down to sleep"
        case "rest":
            return "rests"
        case "wait":
            minutes = started.args.get("minutes")
            return f"waits {minutes} min" if minutes is not None else "waits"
        case "work":
            return f"starts {label}" if label else f"starts work: {started.args.get('task')}"
    return f"{started.action.replace('_', ' ')} {label}".rstrip()


def _doing(action: str, label: str) -> str:
    """The action as an -ing phrase: "walking to the well", "tending the rice paddies", "gathering roots"."""
    match action:
        case "walk_to":
            if label == "your home":
                return "walking home"
            return f"walking {label}" if label.startswith("to ") else (f"walking to {label}" if label else "walking")
        case "work":
            return label or "working"
        case "gather" | "eat" | "follow":
            return f"{_GERUNDS[action]} {label}".rstrip()
        case "drink":
            return f"drinking at {label}" if label else "drinking"
    return _GERUNDS.get(action, action.replace("_", " "))


def _ended(ended: ActionEnded, label: str | None) -> str:
    """Third person, with the label of the action's start when it is known."""
    if label is None:
        doing = _GERUNDS.get(ended.action, ended.action.replace("_", " "))
    else:
        doing = _doing(ended.action, label)
    if ended.outcome == "done":
        if ended.action == "walk_to" and label is not None and not label.startswith("to "):
            return "arrives home" if label == "your home" else f"arrives at {label}"
        if ended.action == "sleep":
            return "wakes up"
        return f"finishes {doing}"
    if ended.outcome == "interrupted":
        return f"stops {doing}"
    return f"fails at {doing}"


def start_labels(session: Session, run_id: str, citizen_id: str, rows: Sequence[Event]) -> dict[int, str]:
    """Labels of the actions the page's `action_finished`/`action_interrupted` rows end, by action number."""
    ended = [
        row for row in rows if row.type in ("action_finished", "action_interrupted") and row.actor_id == citizen_id
    ]
    if not ended:
        return {}
    numbers = {int(row.payload["number"]) for row in ended}
    earliest = min(row.tick for row in ended) - LONGEST_ACTION_TICKS
    statement = select(Event.payload).where(
        Event.run_id == run_id,
        Event.actor_id == citizen_id,
        Event.type == "action_started",
        Event.tick >= earliest,
        Event.tick <= max(row.tick for row in ended),
        col(Event.payload)["number"].as_integer().in_(numbers),
    )
    return {int(payload["number"]): str(payload["label"]) for payload in session.exec(statement).all()}


def _names(ids: Sequence[str], people: dict[str, PersonRef]) -> str:
    named = [people[i].name if i in people else i for i in ids]
    if len(named) <= 1:
        return "".join(named)
    return f"{', '.join(named[:-1])} and {named[-1]}"


def _location(where: ItemLocation, people: dict[str, PersonRef], places: PlaceIndex) -> str:
    match where.kind:
        case "inventory":
            return people[where.id].name if where.id in people else str(where.id)
        case "store":
            return places.store_name(where.id or "")
        case "ground":
            return "the ground"
        case "resource":
            return "the wild"
        case "eaten":
            return "eaten"
    return "the world"


def _moved(moved: ItemMoved, me: str, people: dict[str, PersonRef], places: PlaceIndex) -> str:
    amount = amount_words(moved.count, ITEMS[moved.item]) if moved.item in ITEMS else f"{moved.count} {moved.item}"
    source, destination = moved.source, moved.destination
    mine_from = source.kind == "inventory" and source.id == me
    mine_to = destination.kind == "inventory" and destination.id == me
    if mine_from and destination.kind == "eaten":
        return f"eats {amount}"
    if mine_from and destination.kind == "store":
        return f"puts {amount} in {places.store_name(destination.id or '')}"
    if mine_from and destination.kind == "ground":
        return f"puts down {amount}"
    if mine_from:
        return f"gives {amount} to {_location(destination, people, places)}"
    if mine_to and source.kind == "resource":
        return f"gathers {amount}"
    if mine_to and source.kind == "store":
        return f"takes {amount} from {places.store_name(source.id or '')}"
    if mine_to and source.kind == "ground":
        return f"picks up {amount}"
    if mine_to:
        return f"gets {amount} from {_location(source, people, places)}"
    if source.kind == "world":
        grows = "ripens" if moved.item in ITEMS and ITEMS[moved.item].mass else "ripen"
        return f"{amount} {grows} in {_location(destination, people, places)}"
    return f"{amount} moves from {_location(source, people, places)} to {_location(destination, people, places)}"


def _summary(
    row: Event, me: str, people: dict[str, PersonRef], places: PlaceIndex, labels: dict[int, str], names: Names
) -> tuple[str, str | None, list[str]]:
    payload = row.payload
    match row.type:
        case "citizen_spawned":
            x, y, z = row.position or (0.0, 0.0, 0.0)
            place = places.where((x, y, z)) if row.position else None
            return f"comes into the world{f' at {place.name}' if place else ''}", None, []
        case "action_started":
            return _started(ActionStarted.model_validate(payload)), None, []
        case "action_finished" | "action_interrupted":
            ended = ActionEnded.model_validate(payload)
            return _ended(ended, labels.get(ended.number)), ended.text, []
        case "said":
            said = Said.model_validate(payload)
            if row.actor_id == me:
                verb = {"whisper": "whispers", "normal": "says", "shout": "shouts"}[said.volume]
                heard = f"heard by {_names(said.heard_by, people)}" if said.heard_by else "nobody heard"
                return f'{verb} "{said.words}"', heard, list(said.heard_by)
            speaker = people[row.actor_id].name if row.actor_id in people else "someone"
            return f'hears {speaker}: "{said.words}"', None, [row.actor_id] if row.actor_id else []
        case "need_changed":
            changed = NeedChanged.model_validate(payload)
            return f"feels {changed.level}{'' if changed.worse else ' again'}", None, []
        case "injured":
            injured = Injured.model_validate(payload)
            lost = f"lost {injured.amount:.0f} health"
            if injured.attacker is None:
                return f"is hurt: {injured.cause}", lost, []
            how = "struck" if injured.cause == "violence" else "attacked"
            return (
                f"is {how} by {names(injured.attacker)}",
                lost,
                [injured.attacker] if injured.attacker in people else [],
            )
        case "died":
            died = Died.model_validate(payload)
            if died.attacker is None:
                return f"dies: {died.cause}", None, []
            return f"is killed by {names(died.attacker)}", None, [died.attacker] if died.attacker in people else []
        case "item_moved":
            return _moved(ItemMoved.model_validate(payload), me, people, places), None, []
        case "knowledge_changed":
            learned = KnowledgeChanged.model_validate(payload)
            if learned.about == "person":
                name = people[learned.ref].name if learned.ref in people else learned.ref
                return f"gets to know {name}", None, [learned.ref]
            name = places.place_name(learned.ref)
            if learned.level == "visited":
                return f"comes to {name} for the first time", None, []
            return f"hears of {name}", None, []
        case "perceived":
            return "looks around", Perceived.model_validate(payload).text, []

    told = Told(type=row.type, actor_kind=row.actor_kind, actor_id=row.actor_id, payload=payload)
    return tell(told, names, own=True)[0], None, []


def timeline_entry(
    row: Event, me: str, people: dict[str, PersonRef], places: PlaceIndex, labels: dict[int, str], names: Names
) -> TimelineEntry:
    summary, detail, related = _summary(row, me, people, places, labels, names)
    day, time = town_clock(row.tick)
    return TimelineEntry(
        id=row.id,
        seq=row.seq,
        tick=row.tick,
        day=day,
        time=time,
        type=row.type,
        visibility=row.visibility,
        summary=summary,
        detail=detail,
        related=related,
    )
