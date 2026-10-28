"""The engine process: the only writer of world state. `python -m app.engine` (or `make engine`).

Loads the stored world (current generator version) and the town, resumes the latest run of that world from its
latest snapshot (or starts a new run with the dev cast), then ticks: 1 tick = 1 game minute, `speed` ticks per real
second (1 = real time, up to 60), paused = no ticks. `--headless --ticks N` runs N ticks as fast as possible.
Every tick is one transaction: its events, a snapshot every game hour, the run's clock, and a NOTIFY.
Admin commands (pause, speed) arrive through the `engine_commands` table.
"""

import argparse
import logging
import signal
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType

from sqlalchemy import Engine as DbEngine
from sqlmodel import Session

from app.core.db import create_db_engine
from app.db.models import Run
from app.db.schemas import MAX_SPEED, ClockChange
from app.lib.ulid import UlidFactory
from app.observability.store import EventStore, create_run, discard_after, latest_run, latest_snapshot, pending_commands
from app.sim.citizens import DEV_CITIZENS, load_citizens
from app.sim.clock import TICKS_PER_HOUR
from app.sim.simulation import Simulation
from app.sim.snapshot import SimSnapshot, restore, take_snapshot
from app.sim.world import SimWorld, load_sim_world
from app.world.generate import GENERATOR
from app.world.spec import load_site_kinds, load_world_spec
from app.world.store import WorldKey, world_key

PAUSED_POLL_S = 0.25
APPLICATION_NAME = "pebble-engine"  # the engine's connections in pg_stat_activity
log = logging.getLogger("pebble.engine")

Brain = Callable[[Simulation], None]  # called before every tick (scripted brains arrive with M7)


@dataclass
class Clock:
    speed: int = 1  # ticks per real second
    paused: bool = False

    def apply(self, change: ClockChange) -> None:
        if change.speed is not None:
            self.speed = change.speed
        if change.paused is not None:
            self.paused = change.paused


@dataclass
class EngineLoop:
    sim: Simulation
    store: EventStore
    clock: Clock
    brains: list[Brain] = field(default_factory=list)
    stopping: bool = False

    @property
    def run(self) -> Run:
        return self.store.run

    def tick(self) -> None:
        for brain in self.brains:
            brain(self.sim)
        self.sim.step()
        self.store.write(self.sim.drain())
        if self.sim.tick % TICKS_PER_HOUR == 0:
            self.store.snapshot(take_snapshot(self.sim.state))
        self.store.commit(self.sim.tick, self.clock.speed, self.clock.paused)

    def apply_commands(self) -> None:
        commands = pending_commands(self.store.session, self.run.id)
        for command in commands:
            if command.kind != "clock":
                raise ValueError(f"unknown engine command {command.kind!r}")
            self.clock.apply(ClockChange.model_validate(command.payload))
            command.applied_at = datetime.now(UTC)
            self.store.session.add(command)
            log.info("clock now speed %s, paused %s", self.clock.speed, self.clock.paused)
        if commands:
            self.store.commit(self.sim.tick, self.clock.speed, self.clock.paused)

    def run_ticks(self, ticks: int | None, headless: bool) -> None:
        """Tick until `ticks` have run (None = forever) or a stop signal; headless never sleeps."""
        done = 0
        next_at = time.monotonic()
        while not self.stopping and (ticks is None or done < ticks):
            self.apply_commands()
            if self.clock.paused and not headless:
                self.store.commit(self.sim.tick, self.clock.speed, self.clock.paused)  # heartbeat
                time.sleep(PAUSED_POLL_S)
                next_at = time.monotonic()
                continue
            if not headless:
                delay = next_at - time.monotonic()
                if delay > 0:
                    time.sleep(min(delay, PAUSED_POLL_S))
                    continue
                next_at += 1.0 / self.clock.speed
            started = time.perf_counter()
            self.tick()
            done += 1
            if self.sim.tick % TICKS_PER_HOUR == 0:
                log.info("tick %s (%.1f ms)", self.sim.tick, (time.perf_counter() - started) * 1000)

    def shut_down(self) -> None:
        """Snapshot where we are so a restart loses nothing, and mark the run stopped."""
        if self.sim.tick % TICKS_PER_HOUR != 0:
            self.store.snapshot(take_snapshot(self.sim.state))
        self.store.commit(self.sim.tick, self.clock.speed, self.clock.paused, status="stopped")


def current_world_key() -> WorldKey:
    return world_key(load_world_spec(), load_site_kinds(), GENERATOR.version)


def start_run(
    session: Session,
    world: SimWorld,
    key: WorldKey,
    ids: UlidFactory,
    citizens: Path | None,
    clock: Clock,
) -> EngineLoop:
    """A new run at tick 0 with the given cast, snapshotted before its first tick."""
    run = create_run(session, key, ids, speed=clock.speed, paused=clock.paused)
    sim = Simulation.new(world, seed=key.seed)
    store = EventStore(session, run, ids)
    if citizens is not None:
        for spec in load_citizens(citizens).citizens:
            sim.add_citizen(spec)
    store.write(sim.drain())
    store.snapshot(take_snapshot(sim.state))
    store.commit(0, clock.speed, clock.paused)
    log.info("started run %s with %s citizens", run.id, len(sim.state.citizens))
    return EngineLoop(sim=sim, store=store, clock=clock)


def resume_run(session: Session, world: SimWorld, run: Run, ids: UlidFactory, clock: Clock) -> EngineLoop:
    """Continue a run from its latest snapshot; events after it (an unclean stop) are dropped and re-simulated."""
    snapshot_row = latest_snapshot(session, run.id)
    if snapshot_row is None:
        raise ValueError(f"run {run.id} has no snapshot to resume from")
    snapshot = SimSnapshot.model_validate(snapshot_row.state)
    dropped = discard_after(session, run.id, snapshot_row.last_seq)
    clock.speed, clock.paused = run.speed, run.paused
    sim = Simulation(world, restore(snapshot))
    store = EventStore(session, run, ids)
    store.commit(sim.tick, clock.speed, clock.paused)
    log.info("resumed run %s at tick %s (dropped %s events past the snapshot)", run.id, sim.tick, dropped)
    return EngineLoop(sim=sim, store=store, clock=clock)


def open_loop(
    session: Session,
    world: SimWorld,
    key: WorldKey,
    *,
    new_run: bool,
    citizens: Path | None,
    clock: Clock,
    ids: UlidFactory | None = None,
) -> EngineLoop:
    ids = ids or UlidFactory()
    run = None if new_run else latest_run(session, key)
    if run is None:
        return start_run(session, world, key, ids, citizens, clock)
    return resume_run(session, world, run, ids, clock)


def main(argv: Sequence[str] | None = None, db_engine: DbEngine | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.engine", description=__doc__.splitlines()[0])
    parser.add_argument("--new-run", action="store_true", help="start a new run instead of resuming the latest")
    parser.add_argument("--speed", type=int, default=None, help=f"ticks per real second, 1..{MAX_SPEED}")
    parser.add_argument("--paused", action="store_true", help="start paused")
    parser.add_argument("--headless", action="store_true", help="no sleeping between ticks (fast-forward)")
    parser.add_argument("--ticks", type=int, default=None, help="stop after this many ticks")
    parser.add_argument("--citizens", type=Path, default=DEV_CITIZENS, help="cast for a new run (YAML)")
    parser.add_argument("--no-citizens", action="store_true", help="start a new run with nobody in it")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    clock = Clock(paused=args.paused)
    if args.speed is not None:
        clock.apply(ClockChange(speed=args.speed))
    with Session(db_engine or create_db_engine(APPLICATION_NAME)) as session:
        world = load_sim_world(session)
        loop = open_loop(
            session,
            world,
            current_world_key(),
            new_run=args.new_run,
            citizens=None if args.no_citizens else args.citizens,
            clock=clock,
        )
        if args.speed is not None or args.paused:
            loop.clock.apply(ClockChange(speed=args.speed, paused=True if args.paused else None))

        def stop(signum: int, frame: FrameType | None) -> None:  # noqa: ARG001  # signal handler signature
            loop.stopping = True

        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGTERM, stop)
        loop.run_ticks(args.ticks, headless=args.headless)
        loop.shut_down()
        log.info("stopped run %s at tick %s", loop.run.id, loop.sim.tick)


if __name__ == "__main__":
    main()
