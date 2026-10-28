"""Conversations: `said` events grouped into threads by place and time.

A line joins an open thread when its speaker or one of its hearers is already in the thread and the thread's last
line is at most GAP_TICKS before it; otherwise it starts a new thread. Hearing ranges (30 m talking, 150 m shouting)
keep a thread in one place: it is named after the smallest place its first line was said in (the well, the market)
and the area around it (the castle town, a camp, a landmark).
"""

from dataclasses import dataclass, field

from pydantic import BaseModel
from sqlmodel import Session, col, select

from app.db.models import Event
from app.observability.events import Said
from app.services.citizens import PersonRef, roster
from app.services.clock import run_or_latest
from app.services.places import PlaceIndex, PlaceRef
from app.sim.clock import town_clock
from app.world_api.models import Volume

GAP_TICKS = 10  # game minutes of silence that end a thread
DEFAULT_SPAN = 24 * 60  # the last game day
MAX_THREADS = 200


class Line(BaseModel):
    id: str
    seq: int
    tick: int
    time: str
    speaker: PersonRef
    words: str
    volume: Volume
    heard_by: list[PersonRef]


class Thread(BaseModel):
    id: str  # the first line's event id
    place: PlaceRef | None  # where it began (None = out in the wild)
    area: PlaceRef | None  # the town, camp or landmark it was in
    start_tick: int
    end_tick: int
    day: int
    time: str  # town time of the first line
    speakers: list[PersonRef]
    listeners: list[PersonRef]  # heard something but never spoke
    lines: list[Line]


class ConversationsPage(BaseModel):
    run_id: str
    from_tick: int
    to_tick: int
    threads: list[Thread]  # newest first


@dataclass
class _Open:
    area: PlaceRef | None
    place: PlaceRef | None
    people: set[str]
    lines: list[Line] = field(default_factory=list)


def _person(person_id: str, people: dict[str, PersonRef]) -> PersonRef:
    return people.get(person_id, PersonRef(id=person_id, name=person_id, role=""))


def _thread(open_thread: _Open) -> Thread:
    first, last = open_thread.lines[0], open_thread.lines[-1]
    speakers = {line.speaker.id: line.speaker for line in open_thread.lines}
    heard = {person.id: person for line in open_thread.lines for person in line.heard_by}
    day, time = town_clock(first.tick)
    return Thread(
        id=first.id,
        place=open_thread.place,
        area=open_thread.area,
        start_tick=first.tick,
        end_tick=last.tick,
        day=day,
        time=time,
        speakers=list(speakers.values()),
        listeners=[person for person_id, person in sorted(heard.items()) if person_id not in speakers],
        lines=open_thread.lines,
    )


def list_conversations(
    session: Session,
    places: PlaceIndex,
    *,
    run_id: str | None = None,
    from_tick: int | None = None,
    to_tick: int | None = None,
    place: str | None = None,
    limit: int = 50,
) -> ConversationsPage | None:
    run = run_or_latest(session, run_id)
    if run is None:
        return None
    end = min(run.tick if to_tick is None else to_tick, run.tick)
    start = max(0, end - DEFAULT_SPAN) if from_tick is None else min(from_tick, end)
    people = roster(session, run.id)
    statement = (
        select(Event)
        .where(Event.run_id == run.id, Event.type == "said", Event.tick >= start, Event.tick <= end)
        .order_by(col(Event.seq))
    )
    threads: list[_Open] = []
    for row in session.exec(statement).all():
        said = Said.model_validate(row.payload)
        speaker = row.actor_id or "someone"
        x, y, z = row.position or (0.0, 0.0, 0.0)
        _, time = town_clock(row.tick)
        line = Line(
            id=row.id,
            seq=row.seq,
            tick=row.tick,
            time=time,
            speaker=_person(speaker, people),
            words=said.words,
            volume=said.volume,
            heard_by=[_person(hearer, people) for hearer in said.heard_by],
        )
        involved = {speaker, *said.heard_by}
        joined = next(
            (
                thread
                for thread in reversed(threads)
                if thread.lines[-1].tick >= row.tick - GAP_TICKS and involved & thread.people
            ),
            None,
        )
        if joined is None:
            where, area = (places.where((x, y, z)), places.area((x, y, z))) if row.position else (None, None)
            joined = _Open(area=area, place=where, people=set())
            threads.append(joined)
        joined.lines.append(line)
        joined.people |= involved
    found = [
        _thread(thread)
        for thread in threads
        if place is None or place in {ref.id for ref in (thread.place, thread.area) if ref is not None}
    ]
    return ConversationsPage(run_id=run.id, from_tick=start, to_tick=end, threads=found[::-1][:limit])
