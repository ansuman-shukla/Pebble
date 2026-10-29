"""The engine against Postgres (inside a rolled-back transaction): ticks persist, snapshots resume, commands apply."""

from collections import Counter
from collections.abc import Callable
from typing import Any

import pytest
from sqlmodel import Session, col, select

from app.db.models import EngineCommand, Event, Run, Snapshot
from app.engine import HEARTBEAT_S, POLL_S, Clock, EngineLoop, open_loop
from app.observability.store import latest_snapshot, queue_command
from app.sim.citizens import CITIZENS, DEV_CITIZENS, load_citizens
from app.sim.clock import game_minute
from app.sim.simulation import Simulation
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


def _snapshot_ticks(session: Session, run_id: str) -> list[int]:
    return list(session.exec(select(Snapshot.tick).where(Snapshot.run_id == run_id).order_by(col(Snapshot.tick))))


def test_stopping_a_resumed_run_before_it_ticks_keeps_its_snapshot(db_session: Session, sim_world: SimWorld) -> None:
    first = open_loop(db_session, sim_world, KEY, new_run=True, citizens=DEV_CITIZENS, clock=Clock())
    run_id = first.run.id
    first.run_ticks(90, headless=True)
    first.shut_down()  # off the hour: snapshotted where it stopped
    assert _snapshot_ticks(db_session, run_id) == [0, 60, 90]

    idle = open_loop(db_session, sim_world, KEY, new_run=False, citizens=DEV_CITIZENS, clock=Clock())
    assert idle.sim.tick == 90
    idle.shut_down()  # no tick since the resume: the snapshot at 90 is already there (#68)
    run = db_session.get(Run, run_id)
    assert run is not None and (run.status, run.tick) == ("stopped", 90)
    assert _snapshot_ticks(db_session, run_id) == [0, 60, 90]

    again = open_loop(db_session, sim_world, KEY, new_run=False, citizens=DEV_CITIZENS, clock=Clock())
    again.run_ticks(35, headless=True)
    again.shut_down()
    assert _snapshot_ticks(db_session, run_id) == [0, 60, 90, 120, 125]
    last = latest_snapshot(db_session, run_id)
    assert last is not None
    assert canonical_json(SimSnapshot.model_validate(last.state)) == canonical_json(take_snapshot(again.sim.state))


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
    assert len(loop.sim.state.citizens) == 22
    assert loop.sim.state.stores == {"store-2": {"rice": 400, "wood": 300}} == load_citizens(CITIZENS).stores
    events = _events(db_session, loop.run.id)
    stocked = [e for e in events if e.type == "item_moved"]
    assert [(e.payload["source"]["kind"], e.payload["destination"]["id"], e.payload["item"]) for e in stocked] == [
        ("world", "store-2", "rice"),
        ("world", "store-2", "wood"),
    ]


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


def test_a_run_with_other_system_blocks_is_not_resumed(db_session: Session, sim_world: SimWorld) -> None:
    old = open_loop(db_session, sim_world, KEY, new_run=True, citizens=DEV_CITIZENS, clock=Clock())
    snapshot = latest_snapshot(db_session, old.run.id)
    assert snapshot is not None
    snapshot.state = {**snapshot.state, "systems": {"retired": {"version": 1, "data": None}}}
    db_session.add(snapshot)
    db_session.flush()
    fresh = open_loop(db_session, sim_world, KEY, new_run=False, citizens=DEV_CITIZENS, clock=Clock())
    assert fresh.run.id != old.run.id


class FakeTime:
    """A monotonic clock that only moves when the loop sleeps; `at` runs a callback once the time reaches it."""

    def __init__(self) -> None:
        self.t = 0.0
        self.ticked_at: list[float] = []
        self.at: list[tuple[float, Callable[[], object]]] = []

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        assert seconds > 0
        self.t += seconds
        while self.at and self.t >= self.at[0][0] - 1e-9:
            self.at.pop(0)[1]()

    def brain(self, sim: Simulation) -> None:  # noqa: ARG002  # brains get the simulation
        self.ticked_at.append(self.t)


def _timed_loop(db_session: Session, sim_world: SimWorld, speed: int) -> tuple[EngineLoop, FakeTime]:
    loop = open_loop(db_session, sim_world, KEY, new_run=True, citizens=None, clock=Clock(speed=speed), brains=False)
    fake = FakeTime()
    loop.now, loop.idle_sleep, loop.brains = fake.now, fake.sleep, [fake.brain]
    return loop, fake


@pytest.mark.parametrize(("speed", "interval_s"), [(1, 60.0), (10, 6.0), (60, 1.0), (600, 0.1)])
def test_a_tick_comes_every_60_over_speed_real_seconds(
    db_session: Session, sim_world: SimWorld, speed: int, interval_s: float
) -> None:
    loop, fake = _timed_loop(db_session, sim_world, speed)
    loop.run_ticks(3, headless=False)
    assert fake.ticked_at == pytest.approx([interval_s, 2 * interval_s, 3 * interval_s], abs=1e-6)
    assert loop.sim.tick == 3


def test_a_speed_change_keeps_the_game_seconds_already_passed(db_session: Session, sim_world: SimWorld) -> None:
    loop, fake = _timed_loop(db_session, sim_world, speed=1)
    fake.at = [(30.0, lambda: queue_command(db_session, loop.run.id, "clock", {"speed": 60}))]
    loop.run_ticks(2, headless=False)
    # 30 game seconds at real time, the other 30 at ×60 take half a second; then a tick every second
    assert fake.ticked_at == pytest.approx([30.5, 31.5], abs=1e-6)


def test_paused_time_is_not_game_time(db_session: Session, sim_world: SimWorld) -> None:
    loop, fake = _timed_loop(db_session, sim_world, speed=1)
    fake.at = [
        (30.0, lambda: queue_command(db_session, loop.run.id, "clock", {"paused": True})),
        (130.0, lambda: queue_command(db_session, loop.run.id, "clock", {"paused": False})),
    ]
    loop.run_ticks(1, headless=False)
    assert fake.ticked_at == pytest.approx([160.0], abs=1e-6)


def test_an_engine_waiting_for_its_next_tick_stamps_a_heartbeat_every_second(
    db_session: Session, sim_world: SimWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    loop, fake = _timed_loop(db_session, sim_world, speed=1)
    stamps: list[float] = []
    commit = loop.store.commit

    def stamped(*args: Any, **kwargs: Any) -> None:
        stamps.append(fake.t)
        commit(*args, **kwargs)

    monkeypatch.setattr(loop.store, "commit", stamped)
    loop.run_ticks(1, headless=False)
    assert fake.ticked_at == pytest.approx([60.0])
    gaps = [later - earlier for earlier, later in zip(stamps, stamps[1:], strict=False)]
    assert max(gaps) <= HEARTBEAT_S + POLL_S  # alive within the api's 5 s
    assert 50 <= len(stamps) <= 70  # about once a second, not on every quarter-second poll
