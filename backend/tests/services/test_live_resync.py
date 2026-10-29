"""The live hub after a resumed run rewrote its tail: watching clients resync instead of mixing two histories.

The hub reads with its own connections, so these tests commit for real (`committing_engine` empties the test database
afterwards). The listener thread isn't started: each test drives `_refresh` itself.
"""

import asyncio
import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import Engine
from sqlmodel import Session

from app.db.models import Event, Run
from app.engine import Clock, EngineLoop, open_loop
from app.observability.store import events_after
from app.services.live import LiveHub, Subscriber, load_feed
from app.sim.citizens import DEV_CITIZENS
from app.sim.world import SimWorld
from app.world.store import WorldKey
from app.world_api.facade import WorldApi

KEY = WorldKey(seed=20261028, generator_version="test-live-resync", spec_hash="3" * 64)


@dataclass
class Client:
    subscriber: Subscriber
    snapshot: dict[str, object]
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue[str | None]

    def received(self) -> list[dict[str, object] | None]:
        """Messages handed to this client since the last call (None: reconnect for a fresh snapshot)."""
        self.loop.run_until_complete(asyncio.sleep(0))
        texts = []
        while not self.queue.empty():
            texts.append(self.queue.get_nowait())
        return [None if text is None else json.loads(text) for text in texts]


@pytest.fixture
def hub(committing_engine: Engine, monkeypatch: pytest.MonkeyPatch) -> LiveHub:
    monkeypatch.setattr(LiveHub, "_start", lambda self: None)  # noqa: ARG005  # the tests refresh by hand
    return LiveHub(committing_engine)


@pytest.fixture
def session(committing_engine: Engine) -> Iterator[Session]:
    with Session(committing_engine) as session:
        yield session


@pytest.fixture
def engine_loop(session: Session, sim_world: SimWorld) -> EngineLoop:
    loop = open_loop(session, sim_world, KEY, new_run=True, citizens=DEV_CITIZENS, clock=Clock(), brains=False)
    loop.run_ticks(62, headless=True)  # the hour's snapshot at 60, then ticks 61 and 62 past it
    return loop


def _connect(hub: LiveHub, run_id: str) -> Client:
    loop = asyncio.new_event_loop()
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    subscription = hub.subscribe(run_id, loop, queue)
    assert subscription is not None
    subscriber, snapshot = subscription
    return Client(subscriber, json.loads(snapshot), loop, queue)


def _restart_with_another_tail(session: Session, sim_world: SimWorld, loop: EngineLoop) -> EngineLoop:
    """The engine died without a snapshot; the restart resumes from tick 60 and the tail comes out differently
    (as with new code), so the rewritten events don't line up with the old seqs."""
    resumed = open_loop(session, sim_world, KEY, new_run=False, citizens=DEV_CITIZENS, clock=Clock(), brains=False)
    assert (resumed.run.id, resumed.sim.tick) == (loop.run.id, 60)
    WorldApi(resumed.sim, "dev-genzo").say("A different morning")
    resumed.run_ticks(3, headless=True)
    return resumed


def _fresh_snapshot(session: Session, run_id: str) -> dict[str, object]:
    session.expire_all()
    run = session.get(Run, run_id)
    assert run is not None
    snapshot: dict[str, object] = json.loads(load_feed(session, run).message("snapshot").model_dump_json())
    return snapshot


def test_a_rewritten_tail_sends_watching_clients_to_resync(
    hub: LiveHub, session: Session, sim_world: SimWorld, engine_loop: EngineLoop
) -> None:
    run_id = engine_loop.run.id
    watcher = _connect(hub, run_id)
    assert watcher.snapshot["tick"] == 62
    engine_loop.run_ticks(1, headless=True)
    hub._refresh({run_id})
    assert [m and m["type"] for m in watcher.received()] == ["tick"]  # a plain tick carries on

    _restart_with_another_tail(session, sim_world, engine_loop)
    hub._refresh({run_id})
    assert watcher.received() == [None]
    assert run_id not in hub.feeds and watcher.subscriber not in hub.subscribers

    again = _connect(hub, run_id)
    assert again.snapshot == _fresh_snapshot(session, run_id)
    assert again.snapshot["tick"] == 63


def test_a_client_joining_after_a_rewrite_gets_the_new_history(
    hub: LiveHub, session: Session, sim_world: SimWorld, engine_loop: EngineLoop
) -> None:
    run_id = engine_loop.run.id
    watcher = _connect(hub, run_id)
    _restart_with_another_tail(session, sim_world, engine_loop)

    joiner = _connect(hub, run_id)  # before the listener noticed the rewrite
    assert joiner.snapshot == _fresh_snapshot(session, run_id)
    assert watcher.received() == [None]
    assert hub.subscribers == [joiner.subscriber]
    assert joiner.received() == []


def test_a_rewrite_right_before_the_hub_reads_new_events_still_resyncs(
    hub: LiveHub, session: Session, sim_world: SimWorld, engine_loop: EngineLoop, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = engine_loop.run.id
    watcher = _connect(hub, run_id)
    rewrites: list[EngineLoop] = []

    def rewrite_first(*args: Any, **kwargs: Any) -> Sequence[Event]:
        if not rewrites:  # the engine resumes between whatever the hub checked before and its read of new events
            rewrites.append(_restart_with_another_tail(session, sim_world, engine_loop))
        return events_after(*args, **kwargs)

    monkeypatch.setattr("app.services.live.events_after", rewrite_first)
    hub._refresh({run_id})
    assert rewrites
    assert watcher.received() == [None]
    assert run_id not in hub.feeds
