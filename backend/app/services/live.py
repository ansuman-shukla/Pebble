"""The live feed (M8, first slice): citizens and public events pushed to spectators as the engine ticks.

The engine ends every tick's transaction with `NOTIFY pebble_events` (D45). In the api process one background thread
LISTENs on that channel, keeps a replayed state per followed run (latest snapshot + events, the same reducer as
`/entities?at`), and fans out JSON messages to the WebSocket handlers' asyncio queues:

```
 engine ── NOTIFY {run, tick, seqs} ──▶ listener thread ── fetch events after the last seq ──▶ replay per tick
                                              │                                                     │
             WebSocket /api/v1/live ◀── queue ◀── "event" messages (said, died, action_started/finished)
                                              ◀── one "tick" message per tick (citizens, animals, fires)
```

On connect a client gets a `snapshot` message; when the clock's speed or pause changes without a tick, a `tick`
message with the same tick says so. Clients following the latest run are closed (code 1012) when a newer run starts,
so they reconnect and resync from its snapshot.
"""

import asyncio
import json
import logging
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

import psycopg
from pydantic import BaseModel, Field
from sqlalchemy import Engine
from sqlmodel import Session

from app.db.models import Event, Run
from app.observability.replay import ReplayEvent, ReplayState, apply_event, replay
from app.observability.store import EVENTS_CHANNEL, events_after, latest_run, latest_snapshot
from app.services.entities import AnimalEntity, CitizenEntity, FireEntity, citizen_entity, wild_entities
from app.sim.clock import town_clock
from app.sim.snapshot import SimSnapshot

log = logging.getLogger("pebble.live")

LIVE_EVENT_TYPES = frozenset({"said", "died", "action_started", "action_finished"})
LISTEN_TIMEOUT_S = 1.0  # how often the listener looks at the clock while no ticks arrive (pause, speed changes)
RUN_SWITCHED = None  # queued to clients following the latest run when a newer run starts


class LiveState(BaseModel):
    """Where everyone is: on connect (`snapshot`) and after every engine tick (`tick`)."""

    type: Literal["snapshot", "tick"]
    run_id: str
    tick: int
    day: int
    time: str  # town time "HH:MM"
    speed: float  # ticks (game minutes) per real second
    paused: bool
    citizens: list[CitizenEntity]
    animals: list[AnimalEntity]
    fires: list[FireEntity]


class LiveEventDetail(BaseModel):
    id: str
    type: str  # said | died | action_started | action_finished
    actor_id: str | None
    payload: dict[str, Any]  # typed per event type: app.observability.events.PAYLOAD_TYPES


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
    speed: float
    paused: bool

    def message(self, kind: Literal["snapshot", "tick"]) -> LiveState:
        day, time = town_clock(self.state.tick)
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
            citizens=citizens,
            animals=animals,
            fires=fires,
        )

    def advance(self, session: Session, run: Run) -> list[LiveMessage]:
        """Apply the events stored since the last call: event messages as they come, a tick message after each
        tick's summary (actions taken between ticks are stored with the next tick, before its summary)."""
        messages: list[LiveMessage] = []
        clock_changed = (float(run.speed), run.paused) != (self.speed, self.paused)
        self.speed, self.paused = float(run.speed), run.paused
        for row in events_after(session, self.run_id, self.last_seq):
            apply_event(self.state, _replayable(row))
            self.last_seq = row.seq
            if row.type in LIVE_EVENT_TYPES and row.visibility == "public":
                detail = LiveEventDetail(id=row.id, type=row.type, actor_id=row.actor_id, payload=row.payload)
                messages.append(LiveEvent(type="event", run_id=self.run_id, tick=row.tick, event=detail))
            elif row.type == "tick_summary":
                messages.append(self.message("tick"))
        if not messages and clock_changed:
            messages.append(self.message("tick"))
        return messages


def load_feed(session: Session, run: Run) -> RunFeed:
    snapshot_row = latest_snapshot(session, run.id)
    if snapshot_row is None:
        raise LookupError(f"run {run.id} has no snapshot yet")
    rows = events_after(session, run.id, snapshot_row.last_seq)
    state = replay(SimSnapshot.model_validate(snapshot_row.state), (_replayable(row) for row in rows))
    last_seq = rows[-1].seq if rows else snapshot_row.last_seq
    return RunFeed(run_id=run.id, state=state, last_seq=last_seq, speed=float(run.speed), paused=run.paused)


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
            if feed is None:
                feed = self.feeds[run.id] = load_feed(session, run)
            else:
                self._broadcast(feed.run_id, feed.advance(session, run))  # catch up before the snapshot
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
        """Advance every followed run (all of them on a timeout, to notice clock changes) and spot new runs."""
        with Session(self.db_engine) as session, self.lock:
            for run_id in sorted(set(self.feeds)):
                run = session.get(Run, run_id)
                if run is not None:
                    self._broadcast(run_id, self.feeds[run_id].advance(session, run))
            newcomers = notified - set(self.feeds)
            if newcomers and any(s.follows_latest for s in self.subscribers):
                newest = latest_run(session)
                if newest is not None and newest.id in newcomers:
                    for subscriber in [s for s in self.subscribers if s.follows_latest]:
                        subscriber.send(RUN_SWITCHED)
                        self.subscribers.remove(subscriber)
            self._drop_unwatched()

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
