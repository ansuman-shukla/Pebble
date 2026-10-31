"""The live feed (M8, first slice): citizens and public events pushed to spectators as the engine ticks.

The engine ends every tick's transaction with `NOTIFY pebble_events` (D45). In the api process one background thread
LISTENs on that channel, keeps a replayed state per followed run (latest snapshot + events, the same reducer as
`/entities?at`), and fans out JSON messages to the WebSocket handlers' asyncio queues:

```
 engine ── NOTIFY {run, tick, seqs} ──▶ listener thread ── fetch events after the last seq ──▶ replay per tick
                                              │                                                     │
             WebSocket /api/v1/live ◀── queue ◀── "event" messages (public events with a line worth telling)
                                              ◀── one "tick" message per tick (citizens, animals, fires)
```

On connect a client gets a `snapshot` message; when the clock's speed or pause changes without a tick, a `tick`
message with the same tick says so. Clients are closed (code 1012) to reconnect and resync from a fresh snapshot when
a newer run starts (those following the latest run) or when their run's history past its latest snapshot was rewritten
(an engine resumed after an unclean stop or a lost connection drops that tail and simulates it again; its events get
new ids, and new code can make them come out differently).
"""

import asyncio
import json
import logging
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

import psycopg
from pydantic import BaseModel, Field
from sqlalchemy import Engine
from sqlmodel import Session

from app.db.models import Event, Run
from app.observability.lines import Importance, Names, Resident, Told, namer, tell
from app.observability.replay import ReplayEvent, ReplayState, apply_event, replay
from app.observability.store import EVENTS_CHANNEL, event_id_at, events_after, latest_run, latest_snapshot
from app.services.entities import (
    AnimalEntity,
    CitizenEntity,
    FireEntity,
    Position,
    citizen_entity,
    position,
    snapshot_before,
    tick_elapsed,
    wild_entities,
)
from app.sim.clock import town_clock
from app.sim.nodes import NodeView
from app.sim.snapshot import SimSnapshot

log = logging.getLogger("pebble.live")

# sent whatever their importance (clients follow actions, speech and node stages); any other public event is sent
# when its line is worth telling (importance 1-3)
LIVE_EVENT_TYPES = frozenset({"said", "died", "action_started", "action_finished", "node_changed"})
LISTEN_TIMEOUT_S = 1.0  # how often the listener looks at the clock while no ticks arrive (pause, speed changes)
RESYNC = None  # queued to clients that must reconnect for a fresh snapshot (a newer run, a rewritten history)


class NodeEntity(NodeView):
    id: str  # "flora:<index in GET /world/flora>", a feature's id, or a paddy's ("paddy-1")


class LiveState(BaseModel):
    """Where everyone is: on connect (`snapshot`) and after every engine tick (`tick`)."""

    type: Literal["snapshot", "tick"]
    run_id: str
    tick: int
    day: int
    time: str  # town time "HH:MM"
    speed: float  # game seconds per real second (1 = real time)
    paused: bool
    # game seconds of this tick passed when the message was made (0..60; ~0 on a tick as it happens): a page opened
    # mid-tick draws its walkers that far along their paths, as if it had watched the whole tick (D100)
    tick_elapsed_s: float
    citizens: list[CitizenEntity]
    animals: list[AnimalEntity]
    fires: list[FireEntity]
    # every node that differs from full (10-world-v1 §1.1: a picked bush, a stump, a paddy short of ripe), in
    # `snapshot` messages only; after it each change comes as a `node_changed` event (its `stage` and `after`)
    nodes: list[NodeEntity] = []


class LiveEventDetail(BaseModel):
    id: str
    type: str  # an event type (app.observability.events.EventType)
    actor_id: str | None
    payload: dict[str, Any]  # typed per event type: app.observability.events.PAYLOAD_TYPES
    line: str  # what happened in one line, names not ids (app.observability.lines)
    importance: Importance  # 3 death, attack, theft seen, judgement ... 0 hidden (10-world-v1 §5.4)
    position: Position | None  # where it happened (fly-to), when it happened somewhere


class LiveEvent(BaseModel):
    """A public event of interest, sent just before the `tick` message of its tick."""

    type: Literal["event"]
    run_id: str
    tick: int
    event: LiveEventDetail


LiveMessage = Annotated[LiveState | LiveEvent, Field(discriminator="type")]


@dataclass
class RunFeed:
    """One run's replayed state as far as the events stored so far."""

    run_id: str
    state: ReplayState
    last_seq: int
    last_id: str | None  # the id of the event at last_seq (None: there is none yet)
    speed: float
    paused: bool
    running: bool = True  # the engine runs the run (a stopped engine counts no game time)
    # the tick's game seconds counted at the speed in force until `counted_at` (reset when a tick is written)
    counted_s: float = 0.0
    counted_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def counting(self) -> bool:
        return self.running and not self.paused

    def message(self, kind: Literal["snapshot", "tick"], now: datetime | None = None) -> LiveState:
        day, time = town_clock(self.state.tick)
        now = now or datetime.now(UTC)
        elapsed = tick_elapsed(self.counted_s, self.counted_at, self.speed, not self.counting, now)
        citizens = [citizen_entity(citizen, self.state.tick) for _, citizen in sorted(self.state.citizens.items())]
        animals, fires = wild_entities(self.state)
        return LiveState(
            type=kind,
            run_id=self.run_id,
            tick=self.state.tick,
            day=day,
            time=time,
            speed=self.speed,
            paused=self.paused,
            tick_elapsed_s=elapsed,
            citizens=citizens,
            animals=animals,
            fires=fires,
            nodes=[NodeEntity(id=node_id, **view.model_dump()) for node_id, view in sorted(self.state.nodes.items())]
            if kind == "snapshot"
            else [],
        )

    def advance(self, session: Session, run: Run) -> list[LiveMessage] | None:
        """Apply the events stored since the last call: event messages as they come, a tick message after each
        tick's summary (actions taken between ticks are stored with the next tick, before its summary).

        None if the last event replayed was dropped or replaced since (a resumed engine rewrote the tail): the same
        read fetches it with the new ones, so a rewrite can't slip in between the check and the fetch.
        """
        rows = events_after(session, self.run_id, self.last_seq - 1)
        seen = rows[0] if rows and rows[0].seq == self.last_seq else None
        if (seen.id if seen is not None else None) != self.last_id:
            return None
        messages: list[LiveMessage] = []
        running = run.status == "running"
        clock_changed = (float(run.speed), run.paused, running) != (self.speed, self.paused, self.running)
        if clock_changed:
            now = datetime.now(UTC)
            if running and not self.running:  # a resumed engine counts its first tick afresh
                self.counted_s = 0.0
            else:  # what passed at the old speed stays counted
                self.counted_s = tick_elapsed(self.counted_s, self.counted_at, self.speed, not self.counting, now)
            self.counted_at = now
        self.speed, self.paused, self.running = float(run.speed), run.paused, running
        for row in rows[1:] if seen is not None else rows:
            apply_event(self.state, _replayable(row))
            self.last_seq, self.last_id = row.seq, row.id
            if row.type == "tick_summary":
                self.counted_s, self.counted_at = 0.0, row.real_time
            detail = self.detail(row) if row.visibility == "public" and row.type != "tick_summary" else None
            if detail is not None and (row.type in LIVE_EVENT_TYPES or detail.importance > 0):
                messages.append(LiveEvent(type="event", run_id=self.run_id, tick=row.tick, event=detail))
            elif row.type == "tick_summary":
                messages.append(self.message("tick"))
        if not messages and clock_changed:
            messages.append(self.message("tick"))
        return messages

    def detail(self, row: Event) -> LiveEventDetail:
        """The event as spectators get it: its payload plus its line, importance and place."""
        told = Told(type=row.type, actor_kind=row.actor_kind, actor_id=row.actor_id, payload=row.payload)
        line, importance = tell(told, self.names())
        return LiveEventDetail(
            id=row.id,
            type=row.type,
            actor_id=row.actor_id,
            payload=row.payload,
            line=line,
            importance=importance,
            position=self.where(row),
        )

    def names(self) -> Names:
        """Ids in words for the lines (citizens by name, households, animals, groups: `lines.namer`)."""
        return namer({c.id: Resident(c.name, c.home, c.age) for c in self.state.citizens.values()})

    def where(self, row: Event) -> Position | None:
        """Where the payload says (fires, spawns), else where the actor is (after the event)."""
        payload = row.payload
        if "position" in payload and "height_m" in payload:
            x, y, z = payload["position"]
            return position((x, y, z), payload["height_m"])
        if (citizen := self.state.citizens.get(row.actor_id or "")) is not None:
            return position(citizen.position, citizen.height_m)
        if (animal := self.state.animals.get(row.actor_id or "")) is not None:
            return position(animal.position, animal.height_m)
        return None


def load_feed(session: Session, run: Run) -> RunFeed:
    snapshot_row = latest_snapshot(session, run.id, at_or_before=snapshot_before(run.tick))
    if snapshot_row is None:
        raise LookupError(f"run {run.id} has no snapshot yet")
    rows = events_after(session, run.id, snapshot_row.last_seq)
    state = replay(SimSnapshot.model_validate(snapshot_row.state), (_replayable(row) for row in rows))
    last_seq = rows[-1].seq if rows else snapshot_row.last_seq
    last_id = rows[-1].id if rows else event_id_at(session, run.id, last_seq)
    feed = RunFeed(
        run_id=run.id,
        state=state,
        last_seq=last_seq,
        last_id=last_id,
        speed=float(run.speed),
        paused=run.paused,
        running=run.status == "running",
    )
    written = next((row.real_time for row in reversed(rows) if row.type == "tick_summary"), None)
    if written is not None:
        feed.counted_at = written
    return feed


def _replayable(row: Event) -> ReplayEvent:
    return ReplayEvent(tick=row.tick, type=row.type, actor_id=row.actor_id, payload=row.payload)


Queue = asyncio.Queue[str | None]


@dataclass(eq=False)
class Subscriber:
    loop: asyncio.AbstractEventLoop
    queue: Queue
    run_id: str
    follows_latest: bool

    def send(self, text: str | None) -> bool:
        """Hand a message to the client's event loop; False once that loop is gone."""
        try:
            self.loop.call_soon_threadsafe(self.queue.put_nowait, text)
        except RuntimeError:  # the client's event loop has closed
            return False
        return True


@dataclass
class LiveHub:
    """The api process's listener and fan-out (one per database)."""

    db_engine: Engine
    feeds: dict[str, RunFeed] = field(default_factory=dict)
    subscribers: list[Subscriber] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)
    thread: threading.Thread | None = None

    def subscribe(
        self, run_id: str | None, loop: asyncio.AbstractEventLoop, queue: Queue
    ) -> tuple[Subscriber, str] | None:
        """Register a client; returns it with its `snapshot` message (JSON), or None if there's no such run."""
        self._start()
        with Session(self.db_engine) as session, self.lock:
            run = session.get(Run, run_id) if run_id is not None else latest_run(session)
            if run is None or latest_snapshot(session, run.id) is None:
                return None
            feed = self.feeds.get(run.id)
            if feed is not None:
                messages = feed.advance(session, run)  # catch up before the snapshot
                if messages is None:
                    self._resync(run.id)
                    feed = None
                else:
                    self._broadcast(run.id, messages)
            if feed is None:
                feed = self.feeds[run.id] = load_feed(session, run)
            subscriber = Subscriber(loop, queue, run.id, follows_latest=run_id is None)
            self.subscribers.append(subscriber)
            return subscriber, feed.message("snapshot").model_dump_json()

    def unsubscribe(self, subscriber: Subscriber) -> None:
        with self.lock:
            if subscriber in self.subscribers:
                self.subscribers.remove(subscriber)
            self._drop_unwatched()

    # --- the listener thread ---

    def _start(self) -> None:
        with self.lock:
            if self.thread is not None and self.thread.is_alive():
                return
            self.thread = threading.Thread(target=self._listen_forever, name="pebble-live", daemon=True)
            self.thread.start()

    def _listen_forever(self) -> None:
        while True:
            try:
                self._listen()
            except psycopg.OperationalError:  # the database went away: try again shortly
                log.exception("live feed lost its database connection; reconnecting")
                threading.Event().wait(LISTEN_TIMEOUT_S)

    def _listen(self) -> None:
        conninfo = self.db_engine.url.set(drivername="postgresql").render_as_string(hide_password=False)
        with psycopg.connect(conninfo, autocommit=True) as connection:
            connection.execute(f"LISTEN {EVENTS_CHANNEL}")
            while True:
                runs = {json.loads(notice.payload)["run_id"] for notice in _notices(connection)}
                self._refresh(runs)

    def _refresh(self, notified: set[str]) -> None:
        """Advance every followed run (all of them on a timeout, to notice clock changes), resync the ones whose
        history was rewritten and spot new runs."""
        with Session(self.db_engine) as session, self.lock:
            for run_id in sorted(set(self.feeds)):
                run = session.get(Run, run_id)
                if run is None:
                    continue
                messages = self.feeds[run_id].advance(session, run)
                if messages is None:
                    self._resync(run_id)
                else:
                    self._broadcast(run_id, messages)
            newcomers = notified - set(self.feeds)
            if newcomers and any(s.follows_latest for s in self.subscribers):
                newest = latest_run(session)
                if newest is not None and newest.id in newcomers:
                    self._close([s for s in self.subscribers if s.follows_latest])
            self._drop_unwatched()

    def _resync(self, run_id: str) -> None:
        """Send the run's clients off to reconnect and forget its replayed state."""
        self._close([s for s in self.subscribers if s.run_id == run_id])
        del self.feeds[run_id]

    def _close(self, subscribers: list[Subscriber]) -> None:
        for subscriber in subscribers:
            subscriber.send(RESYNC)
            self.subscribers.remove(subscriber)

    def _broadcast(self, run_id: str, messages: list[LiveMessage]) -> None:
        texts = [message.model_dump_json() for message in messages]
        for subscriber in [s for s in self.subscribers if s.run_id == run_id]:
            for text in texts:
                if not subscriber.send(text):
                    self.subscribers.remove(subscriber)
                    break

    def _drop_unwatched(self) -> None:
        watched = {s.run_id for s in self.subscribers}
        for run_id in set(self.feeds) - watched:
            del self.feeds[run_id]


def _notices(connection: psycopg.Connection[Any]) -> Iterator[psycopg.Notify]:
    """The next notification(s) as soon as they arrive, or none after LISTEN_TIMEOUT_S."""
    yield from connection.notifies(timeout=LISTEN_TIMEOUT_S, stop_after=1)


_HUBS: dict[str, LiveHub] = {}
_HUBS_LOCK = threading.Lock()


def live_hub(db_engine: Engine) -> LiveHub:
    key = db_engine.url.render_as_string(hide_password=False)
    with _HUBS_LOCK:
        hub = _HUBS.get(key)
        if hub is None:
            hub = _HUBS[key] = LiveHub(db_engine)
        return hub
