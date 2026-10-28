"""The engine against Postgres (inside a rolled-back transaction): ticks persist, snapshots resume, commands apply."""

from collections import Counter
from typing import Any

from sqlmodel import Session, col, select

from app.db.models import EngineCommand, Event, Run, Snapshot
from app.engine import Clock, open_loop
from app.observability.store import latest_snapshot, queue_command
from app.sim.citizens import CITIZENS, DEV_CITIZENS, load_citizens
from app.sim.clock import game_minute
from app.sim.snapshot import SimSnapshot, canonical_json, take_snapshot
from app.sim.world import SimWorld
from app.world.store import WorldKey

KEY = WorldKey(seed=20261028, generator_version="test", spec_hash="0" * 64)


def _events(session: Session, run_id: str) -> list[Event]:
    return list(session.exec(select(Event).where(Event.run_id == run_id).order_by(col(Event.seq))).all())


def _comparable(events: list[Event]) -> list[tuple[Any, ...]]:
    return [(e.seq, e.tick, e.type, e.actor_id, e.cell, e.position, e.payload) for e in events]


def test_engine_smoke_runs_120_ticks_headless_and_persists_them(db_session: Session, sim_world: SimWorld) -> None:
    loop = open_loop(db_session, sim_world, KEY, new_run=True, citizens=DEV_CITIZENS, clock=Clock())
    loop.run_ticks(120, headless=True)

    run = db_session.get(Run, loop.run.id)
    assert run is not None and (run.tick, run.status, run.world_seed) == (120, "running", KEY.seed)
    events = _events(db_session, run.id)
    counts = Counter(e.type for e in events)
    assert counts["tick_summary"] == 120
    assert counts["citizen_spawned"] == len(load_citizens().citizens)
    assert [e.seq for e in events] == list(range(1, len(events) + 1))
    assert all(e.game_time == game_minute(e.tick) and e.world_seed == KEY.seed for e in events)
    assert len({e.id for e in events}) == len(events) and [e.id for e in events] == sorted(e.id for e in events)
    by_id = {e.id: e for e in events}
    caused = [e for e in events if e.cause_id is not None]
    assert all(by_id[e.cause_id].seq < e.seq for e in caused if e.cause_id is not None)

    snapshots = db_session.exec(select(Snapshot.tick).where(Snapshot.run_id == run.id).order_by(col(Snapshot.tick)))
    assert list(snapshots) == [0, 60, 120]
    last = latest_snapshot(db_session, run.id)
    assert last is not None and last.last_seq == events[-1].seq
    assert canonical_json(SimSnapshot.model_validate(last.state)) == canonical_json(take_snapshot(loop.sim.state))


def test_a_run_resumes_from_its_snapshot_and_replays_the_lost_tail(db_session: Session, sim_world: SimWorld) -> None:
    first = open_loop(db_session, sim_world, KEY, new_run=True, citizens=DEV_CITIZENS, clock=Clock(speed=7))
    first.run_ticks(90, headless=True)  # stops without shutting down: ticks 61..90 aren't in a snapshot
    run_id = first.run.id
    tail = [e for e in _events(db_session, run_id) if e.tick > 60]
    assert tail

    resumed = open_loop(db_session, sim_world, KEY, new_run=False, citizens=DEV_CITIZENS, clock=Clock())
    assert resumed.run.id == run_id
    assert resumed.sim.tick == 60
    assert resumed.clock.speed == 7
    assert [e for e in _events(db_session, run_id) if e.tick > 60] == []
    resumed.run_ticks(30, headless=True)
    assert _comparable([e for e in _events(db_session, run_id) if e.tick > 60]) == _comparable(tail)

    resumed.shut_down()
    run = db_session.get(Run, run_id)
    assert run is not None and run.status == "stopped"
    assert latest_snapshot(db_session, run_id) is not None


def test_clock_commands_reach_the_engine(db_session: Session, sim_world: SimWorld) -> None:
    loop = open_loop(db_session, sim_world, KEY, new_run=True, citizens=None, clock=Clock())
    command = queue_command(db_session, loop.run.id, "clock", {"paused": True, "speed": 30})
    loop.apply_commands()
    assert (loop.clock.paused, loop.clock.speed) == (True, 30)
    stored = db_session.get(EngineCommand, command.id)
    assert stored is not None and stored.applied_at is not None
    run = db_session.get(Run, loop.run.id)
    assert run is not None and (run.paused, run.speed) == (True, 30)
    loop.run_ticks(3, headless=True)  # headless ignores pause; real time would wait
    assert loop.sim.tick == 3


def test_a_new_run_starts_with_the_cast_and_the_stocked_storehouse(db_session: Session, sim_world: SimWorld) -> None:
    loop = open_loop(db_session, sim_world, KEY, new_run=True, citizens=CITIZENS, clock=Clock())
    assert len(loop.sim.state.citizens) == 15
    assert loop.sim.state.stores == {"store-2": {"rice": load_citizens(CITIZENS).stores["store-2"]["rice"]}}
    events = _events(db_session, loop.run.id)
    stocked = [e for e in events if e.type == "item_moved"]
    assert [(e.payload["source"]["kind"], e.payload["destination"]["id"]) for e in stocked] == [("world", "store-2")]


def test_a_run_from_an_older_simulation_is_not_resumed(db_session: Session, sim_world: SimWorld) -> None:
    old = open_loop(db_session, sim_world, KEY, new_run=True, citizens=DEV_CITIZENS, clock=Clock())
    snapshot = latest_snapshot(db_session, old.run.id)
    assert snapshot is not None
    snapshot.state = {**snapshot.state, "version": 1}
    db_session.add(snapshot)
    db_session.flush()
    fresh = open_loop(db_session, sim_world, KEY, new_run=False, citizens=DEV_CITIZENS, clock=Clock())
    assert fresh.run.id != old.run.id
    assert fresh.sim.tick == 0
    again = open_loop(db_session, sim_world, KEY, new_run=False, citizens=DEV_CITIZENS, clock=Clock())
    assert again.run.id == fresh.run.id  # the current one resumes
