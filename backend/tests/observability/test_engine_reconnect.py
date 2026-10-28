"""The engine survives its database connection being terminated, and still crashes on every other error.

The reconnect tests really commit (a terminated backend loses its open transaction) in `pebble_test`, and terminate
only the backends of their own engine, found by a per-test `application_name`.
"""

import logging
import time
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError, OperationalError, ProgrammingError
from sqlmodel import Session, col, create_engine, select

from app.core.db import create_db_engine
from app.db.models import Event, Run, Snapshot
from app.engine import RETRY_FIRST_S, RETRY_MAX_S, Clock, EngineLoop, is_connection_loss, open_loop
from app.sim.citizens import DEV_CITIZENS
from app.sim.simulation import Simulation
from app.sim.snapshot import state_hash
from app.sim.world import SimWorld
from app.world.store import WorldKey

KEY = WorldKey(seed=20261028, generator_version="test", spec_hash="2" * 64)


class NamedEngine:
    """An engine whose connections carry a unique application_name, so a test can terminate exactly those."""

    def __init__(self) -> None:
        self.name = f"pebble-engine-test-{uuid4().hex[:12]}"
        self.engine = create_db_engine(self.name)

    def terminate(self, admin: Engine) -> int:
        statement = text(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity"
            " WHERE datname = current_database() AND application_name = :name"
        )
        with admin.connect() as connection:
            killed = connection.execute(statement, {"name": self.name}).all()
            connection.commit()
        return len(killed)


class KillBefore:
    """A brain that terminates the engine's connections once, before the tick after each of the given ticks."""

    def __init__(self, target: NamedEngine, admin: Engine, ticks: set[int]) -> None:
        self.target, self.admin, self.pending = target, admin, set(ticks)
        self.killed: list[int] = []

    def __call__(self, sim: Simulation) -> None:
        if sim.tick in self.pending:
            self.pending.remove(sim.tick)
            assert self.target.terminate(self.admin) >= 1  # the loop's open transaction is on one of them
            self.killed.append(sim.tick)


class Sleeps:
    def __init__(self) -> None:
        self.delays: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


@pytest.fixture
def named() -> Iterator[NamedEngine]:  # its tests also take committing_engine, which empties the tables after
    target = NamedEngine()
    yield target
    target.engine.dispose()


def _comparable(session: Session, run_id: str) -> list[tuple[Any, ...]]:
    events = session.exec(select(Event).where(Event.run_id == run_id).order_by(col(Event.seq))).all()
    return [(e.seq, e.tick, e.type, e.actor_id, e.cell, e.position, e.payload) for e in events]


def _uninterrupted(sim_world: SimWorld, db: Engine, ticks: int) -> tuple[str, list[tuple[Any, ...]]]:
    with Session(db) as session:
        loop = open_loop(session, sim_world, KEY, new_run=True, citizens=DEV_CITIZENS, clock=Clock())
        loop.run_ticks(ticks, headless=True)
        return state_hash(loop.sim.state), _comparable(session, loop.run.id)


def _open(session: Session, sim_world: SimWorld, sleeps: Sleeps, *brains: Any) -> EngineLoop:
    loop = open_loop(session, sim_world, KEY, new_run=True, citizens=DEV_CITIZENS, clock=Clock())
    loop.brains.extend(brains)
    loop.retry_sleep = sleeps
    return loop


def test_a_terminated_connection_mid_run_resumes_from_the_last_commit_identically(
    named: NamedEngine, committing_engine: Engine, sim_world: SimWorld, caplog: pytest.LogCaptureFixture
) -> None:
    kills = KillBefore(named, committing_engine, {74, 130})  # mid-hour: ticks back to the hour's snapshot replay
    sleeps = Sleeps()
    with Session(named.engine) as session, caplog.at_level(logging.WARNING, logger="pebble.engine"):
        loop = _open(session, sim_world, sleeps, kills)
        loop.run_ticks(150, headless=True)
        final_hash, run_id = state_hash(loop.sim.state), loop.run.id

    assert kills.killed == [74, 130]
    assert sleeps.delays == [RETRY_FIRST_S, RETRY_FIRST_S]  # one reconnect per kill, each on its first attempt
    assert sum("AdminShutdown" in message for message in caplog.messages) == 2

    with Session(committing_engine) as session:
        run = session.get(Run, run_id)
        assert run is not None and (run.tick, run.status) == (150, "running")
        events = _comparable(session, run_id)
        assert [e[0] for e in events] == list(range(1, len(events) + 1))  # seq contiguous: nothing lost or doubled
        assert [e[1] for e in events if e[2] == "tick_summary"] == list(range(1, 151))
        snapshots = session.exec(select(Snapshot.tick).where(Snapshot.run_id == run_id).order_by(col(Snapshot.tick)))
        assert list(snapshots) == [0, 60, 120]

    reference_hash, reference_events = _uninterrupted(sim_world, committing_engine, 150)
    assert final_hash == reference_hash
    assert events == reference_events


def _connect_error() -> OperationalError:
    """A real 'server unreachable' error: nothing listens on port 1."""
    dead = create_engine(create_db_engine().url.set(port=1), connect_args={"connect_timeout": 1})
    with pytest.raises(OperationalError) as caught:
        dead.connect()
    dead.dispose()
    return caught.value


def test_reconnecting_backs_off_until_the_database_is_back(
    named: NamedEngine, committing_engine: Engine, sim_world: SimWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    down = _connect_error()
    assert is_connection_loss(down)
    real_reload = EngineLoop.reload
    failures = iter(range(7))

    def reload_while_down(self: EngineLoop) -> None:
        if next(failures, None) is not None:
            raise down
        real_reload(self)

    monkeypatch.setattr(EngineLoop, "reload", reload_while_down)
    sleeps = Sleeps()
    with Session(named.engine) as session:
        loop = _open(session, sim_world, sleeps, KillBefore(named, committing_engine, {30}))
        loop.run_ticks(40, headless=True)
        final_hash = state_hash(loop.sim.state)

    assert sleeps.delays == [0.5, 1.0, 2.0, 4.0, 8.0, RETRY_MAX_S, RETRY_MAX_S, RETRY_MAX_S]
    assert final_hash == _uninterrupted(sim_world, committing_engine, 40)[0]


def test_a_stop_signal_during_an_outage_ends_the_retries(
    named: NamedEngine, committing_engine: Engine, sim_world: SimWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    down = _connect_error()

    def always_down(_loop: EngineLoop) -> None:
        raise down

    monkeypatch.setattr(EngineLoop, "reload", always_down)
    with Session(named.engine) as session:
        loop = _open(session, sim_world, Sleeps(), KillBefore(named, committing_engine, {5}))

        def sleep_then_stop(seconds: float) -> None:
            sleeps.delays.append(seconds)
            loop.stopping = len(sleeps.delays) == 2

        sleeps = Sleeps()
        loop.retry_sleep = sleep_then_stop
        with pytest.raises(OperationalError) as caught:
            loop.run_ticks(10, headless=True)
    assert caught.value is down
    assert sleeps.delays == [0.5, 1.0]


def test_a_bad_statement_while_reconnecting_crashes(
    named: NamedEngine, committing_engine: Engine, sim_world: SimWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken_reload(self: EngineLoop) -> None:
        self.store.session.close()
        self.store.session.execute(text("SELECT * FROM no_such_table"))

    monkeypatch.setattr(EngineLoop, "reload", broken_reload)
    sleeps = Sleeps()
    with Session(named.engine) as session:
        loop = _open(session, sim_world, sleeps, KillBefore(named, committing_engine, {5}))
        with pytest.raises(ProgrammingError):
            loop.run_ticks(10, headless=True)
    assert sleeps.delays == [RETRY_FIRST_S]


def test_lost_ticks_are_caught_up_without_real_time_waits(
    named: NamedEngine, committing_engine: Engine, sim_world: SimWorld
) -> None:
    sleeps = Sleeps()
    with Session(named.engine) as session:
        loop = _open(session, sim_world, sleeps)
        loop.run_ticks(70, headless=True)
        loop.brains.append(KillBefore(named, committing_engine, {70}))
        loop.clock.speed = 2
        started = time.monotonic()
        loop.run_ticks(2, headless=False)  # back to tick 60, ticks 61..70 at once, then 71 and 72 in real time
        elapsed = time.monotonic() - started
        assert loop.sim.tick == 72 and loop.catch_up_to == 70
    assert sleeps.delays == [RETRY_FIRST_S]
    assert elapsed < 3.0  # waiting for each re-simulated tick at speed 2 would take over 6 s


def test_a_bad_statement_crashes_the_loop(db_session: Session, sim_world: SimWorld) -> None:
    def broken_brain(sim: Simulation) -> None:
        if sim.tick == 3:
            db_session.execute(text("SELECT * FROM no_such_table"))

    sleeps = Sleeps()
    loop = _open(db_session, sim_world, sleeps, broken_brain)
    with pytest.raises(ProgrammingError):
        loop.run_ticks(10, headless=True)
    assert sleeps.delays == []


def test_a_statement_timeout_is_not_a_lost_connection(db_session: Session, sim_world: SimWorld) -> None:
    def slow_brain(sim: Simulation) -> None:
        if sim.tick == 3:
            db_session.execute(text("SET LOCAL statement_timeout = 10"))
            db_session.execute(text("SELECT pg_sleep(1)"))

    sleeps = Sleeps()
    loop = _open(db_session, sim_world, sleeps, slow_brain)
    with pytest.raises(OperationalError) as caught:  # QueryCanceled is an OperationalError, but the server is fine
        loop.run_ticks(10, headless=True)
    assert not is_connection_loss(caught.value)
    assert sleeps.delays == []


def test_programming_errors_in_brains_still_crash(db_session: Session, sim_world: SimWorld) -> None:
    def buggy_brain(sim: Simulation) -> None:
        if sim.tick == 3:
            raise KeyError("dev-nobody")

    loop = _open(db_session, sim_world, Sleeps(), buggy_brain)
    with pytest.raises(KeyError):
        loop.run_ticks(10, headless=True)


def test_only_driver_operational_errors_without_a_server_state_count_as_unreachable() -> None:
    assert is_connection_loss(DBAPIError("SELECT 1", {}, psycopg.OperationalError("connection is lost")))
    closed = psycopg.InterfaceError("the connection is closed")  # SQLAlchemy saw the connection break
    assert is_connection_loss(DBAPIError("SELECT 1", {}, closed, connection_invalidated=True))
    assert not is_connection_loss(DBAPIError("SELECT 1", {}, closed))
    assert not is_connection_loss(DBAPIError("SELECT 1", {}, psycopg.ProgrammingError("wrong parameter count")))
    assert not is_connection_loss(DBAPIError("SELECT 1", {}, ValueError("not a driver error")))
