"""The engine process: the only writer of world state. `python -m app.engine` (or `make engine`).

Loads the stored world (current generator version) and the town, resumes the latest run of that world from its
latest snapshot (or starts a new run with the 15 citizens of `data/citizens/citizens.yaml`), then ticks:
1 tick = 1 game minute, `speed` ticks per real second (1 = real time, up to 60), paused = no ticks.
`--headless --ticks N` runs N ticks as fast as possible.
Every tick is one transaction: its events, a snapshot every game hour, the run's clock, and a NOTIFY.
Admin commands (pause, speed) arrive through the `engine_commands` table.
If the database connection drops (Postgres restarts, a backend is terminated), the engine reconnects with backoff and
reloads the last committed state through the resume path, so the world carries on where the database left it.
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

import psycopg
from sqlalchemy import Engine as DbEngine
from sqlalchemy.exc import DBAPIError
from sqlmodel import Session

from app.brains.profile import BrainProfile
from app.brains.runner import CitizenBrains
from app.core.db import create_db_engine
from app.db.models import Run
from app.db.schemas import MAX_SPEED, ClockChange
from app.lib.ulid import UlidFactory
from app.observability.store import EventStore, create_run, discard_after, latest_run, latest_snapshot, pending_commands
from app.sim.citizens import CITIZENS, load_citizens
from app.sim.clock import TICKS_PER_HOUR
from app.sim.navigation import Planner
from app.sim.simulation import Simulation
from app.sim.snapshot import SNAPSHOT_VERSION, SimSnapshot, restore, take_snapshot
from app.sim.world import SimWorld, load_sim_world
from app.world.generate import GENERATOR
from app.world.spec import load_site_kinds, load_world_spec
from app.world.store import WorldKey, world_key
from app.world_api.facade import WorldApi

PAUSED_POLL_S = 0.25
RETRY_FIRST_S = 0.5  # reconnect backoff: doubles per failed attempt up to the cap, forever
RETRY_MAX_S = 10.0
APPLICATION_NAME = "pebble-engine"  # the engine's connections in pg_stat_activity
# SQLSTATE classes of a lost database: 08 connection exception, 57P operator intervention (shutdown, starting up)
LOST_DATABASE_STATES = ("08", "57P")
log = logging.getLogger("pebble.engine")

Brain = Callable[[Simulation], None]  # called before every tick
HOME_AREAS = {"town": "town", "band_a": "band_a_camp", "band_b": "band_b_camp"}  # region -> its home place id


def citizen_brains(sim: Simulation, seed: int) -> CitizenBrains:
    """A scripted brain for every citizen, acting through their own `WorldApi`."""
    places = sim.world.places
    return CitizenBrains(
        (
            (
                WorldApi(sim, citizen.id),
                BrainProfile(
                    citizen_id=citizen.id,
                    name=citizen.name,
                    role=citizen.role,
                    region=citizen.region,
                    home_area=places[HOME_AREAS[citizen.region]].name,
                ),
            )
            for citizen in sim.core.citizens()
        ),
        seed,
    )


def is_connection_loss(error: DBAPIError) -> bool:
    """The database went away (backend terminated, server restarting or unreachable), not a bad statement."""
    if error.connection_invalidated:
        return True
    if not isinstance(error.orig, psycopg.OperationalError):
        return False
    state = error.orig.sqlstate
    return state is None or state.startswith(LOST_DATABASE_STATES)  # no state: the client couldn't reach the server


def _reason(error: DBAPIError) -> str:
    """The driver's error class and first message line (server text, host and port; never the password)."""
    message = str(error.orig).strip().splitlines()
    return f"{type(error.orig).__name__}: {message[0] if message else ''}"


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
    catch_up_to: int = 0  # ticks below this were committed before a reload; they are re-simulated without waiting
    retry_sleep: Callable[[float], None] = time.sleep
    idle_sleep: Callable[[float], None] = time.sleep  # waiting for the next tick or while paused

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
        """Poll `engine_commands` in a short transaction of its own, so none stays open while the loop waits."""
        commands = pending_commands(self.store.session, self.store.run_id)
        for command in commands:
            if command.kind != "clock":
                raise ValueError(f"unknown engine command {command.kind!r}")
            self.clock.apply(ClockChange.model_validate(command.payload))
            command.applied_at = datetime.now(UTC)
            self.store.session.add(command)
            log.info("clock now speed %s, paused %s", self.clock.speed, self.clock.paused)
        if commands:
            self.store.commit(self.sim.tick, self.clock.speed, self.clock.paused)
        else:
            self.store.session.commit()  # ends the read and hands the connection back to the pool (pre-pinged)

    def run_ticks(self, ticks: int | None, headless: bool) -> None:
        """Tick until `ticks` more ticks have run (None = forever) or a stop signal; headless never sleeps.

        A lost database connection reloads the last committed state and carries on toward the same final tick.
        """
        until = None if ticks is None else self.sim.tick + ticks
        next_at = time.monotonic()
        while not self.stopping and (until is None or self.sim.tick < until):
            try:
                next_at = self._advance(next_at, headless)
            except DBAPIError as error:
                if not is_connection_loss(error):
                    raise
                self.recover(error)
                next_at = time.monotonic()

    def _advance(self, next_at: float, headless: bool) -> float:
        """One pass of the loop: apply commands, then tick, wait or heartbeat. Returns when the next tick is due."""
        self.apply_commands()
        realtime = not headless and self.sim.tick >= self.catch_up_to
        if self.clock.paused and realtime:
            self.store.commit(self.sim.tick, self.clock.speed, self.clock.paused)  # heartbeat
            self.idle_sleep(PAUSED_POLL_S)
            return time.monotonic()
        if realtime:
            delay = next_at - time.monotonic()
            if delay > 0:
                self.idle_sleep(min(delay, PAUSED_POLL_S))
                return next_at
            next_at += 1.0 / self.clock.speed
        started = time.perf_counter()
        self.tick()
        if self.sim.tick % TICKS_PER_HOUR == 0:
            log.info("tick %s (%.1f ms)", self.sim.tick, (time.perf_counter() - started) * 1000)
        return next_at

    def recover(self, error: DBAPIError) -> None:
        """Wait for the database (backoff from RETRY_FIRST_S to RETRY_MAX_S), then reload its last committed state."""
        delay = RETRY_FIRST_S
        attempt = 1
        while True:
            if self.stopping:
                raise error
            log.warning("database connection lost (%s); reconnect attempt %s in %.1f s", _reason(error), attempt, delay)
            self.retry_sleep(delay)
            try:
                self.reload()
            except DBAPIError as again:
                if not is_connection_loss(again):
                    raise
                error = again
                delay = min(delay * 2, RETRY_MAX_S)
                attempt += 1
                continue
            log.warning("reconnected after %s attempt(s); re-simulating up to tick %s", attempt, self.catch_up_to)
            return

    def reload(self) -> None:
        """Rebuild the simulation from the database through the resume path: latest snapshot, later ticks re-simulated.

        The tick that failed never committed (or did, if only the reply was lost), so in memory may be ahead of the
        database; the database wins. Ticks it had committed past the snapshot are caught up without real-time waits.
        """
        session = self.store.session
        session.close()  # drops the broken transaction and its connection; the pool pre-pings the next one
        run = session.get(Run, self.store.run_id)
        if run is None:
            raise ValueError(f"run {self.store.run_id} vanished from the database")
        committed_tick = run.tick
        fresh = resume_run(
            session, self.sim.world, run, self.store.ids, self.clock, planner=self.sim.core.planner, brains=False
        )
        self.sim, self.store = fresh.sim, fresh.store
        # citizens' brains act through WorldApis bound to a simulation: rebuild them on the fresh one (their notes
        # came back with the snapshot); other hooks carry on as they are
        self.brains = [
            citizen_brains(fresh.sim, run.world_seed) if isinstance(hook, CitizenBrains) else hook
            for hook in self.brains
        ]
        self.catch_up_to = committed_tick

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
    brains: bool = True,
) -> EngineLoop:
    """A new run at tick 0 with the given cast, snapshotted before its first tick."""
    run = create_run(session, key, ids, speed=clock.speed, paused=clock.paused)
    sim = Simulation.new(world, seed=key.seed)
    store = EventStore(session, run, ids)
    if citizens is not None:
        cast = load_citizens(citizens)
        for store_id, items in sorted(cast.stores.items()):
            for item, count in sorted(items.items()):
                sim.stock_store(store_id, item, count)
        for spec in cast.citizens:
            sim.add_citizen(spec)
    store.write(sim.drain())
    store.snapshot(take_snapshot(sim.state))
    store.commit(0, clock.speed, clock.paused)
    log.info("started run %s with %s citizens", run.id, len(sim.state.citizens))
    return EngineLoop(sim=sim, store=store, clock=clock, brains=[citizen_brains(sim, key.seed)] if brains else [])


def resume_run(
    session: Session,
    world: SimWorld,
    run: Run,
    ids: UlidFactory,
    clock: Clock,
    planner: Planner | None = None,
    brains: bool = True,
) -> EngineLoop:
    """Continue a run from its latest snapshot; events after it (an unclean stop) are dropped and re-simulated."""
    snapshot_row = latest_snapshot(session, run.id)
    if snapshot_row is None:
        raise ValueError(f"run {run.id} has no snapshot to resume from")
    snapshot = SimSnapshot.model_validate(snapshot_row.state)
    dropped = discard_after(session, run.id, snapshot_row.last_seq)
    clock.speed, clock.paused = run.speed, run.paused
    sim = Simulation(world, restore(snapshot), planner)
    store = EventStore(session, run, ids)
    store.commit(sim.tick, clock.speed, clock.paused)
    log.info("resumed run %s at tick %s (dropped %s events past the snapshot)", run.id, sim.tick, dropped)
    hooks: list[Brain] = [citizen_brains(sim, run.world_seed)] if brains else []
    return EngineLoop(sim=sim, store=store, clock=clock, brains=hooks)


def open_loop(
    session: Session,
    world: SimWorld,
    key: WorldKey,
    *,
    new_run: bool,
    citizens: Path | None,
    clock: Clock,
    ids: UlidFactory | None = None,
    brains: bool = True,
) -> EngineLoop:
    ids = ids or UlidFactory()
    run = None if new_run else latest_run(session, key)
    if run is not None and not resumable(session, run):
        log.info("run %s was written by an older simulation; starting a new one", run.id)
        run = None
    if run is None:
        return start_run(session, world, key, ids, citizens, clock, brains)
    return resume_run(session, world, run, ids, clock, brains=brains)


def resumable(session: Session, run: Run) -> bool:
    """Whether this simulation can continue the run (its latest snapshot has the current snapshot version)."""
    snapshot_row = latest_snapshot(session, run.id)
    return snapshot_row is not None and snapshot_row.state.get("version") == SNAPSHOT_VERSION


def main(argv: Sequence[str] | None = None, db_engine: DbEngine | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.engine", description=__doc__.splitlines()[0])
    parser.add_argument("--new-run", action="store_true", help="start a new run instead of resuming the latest")
    parser.add_argument("--speed", type=int, default=None, help=f"ticks per real second, 1..{MAX_SPEED}")
    parser.add_argument("--paused", action="store_true", help="start paused")
    parser.add_argument("--headless", action="store_true", help="no sleeping between ticks (fast-forward)")
    parser.add_argument("--ticks", type=int, default=None, help="stop after this many ticks")
    parser.add_argument("--citizens", type=Path, default=CITIZENS, help="cast for a new run (YAML)")
    parser.add_argument("--no-citizens", action="store_true", help="start a new run with nobody in it")
    parser.add_argument("--no-brains", action="store_true", help="citizens do nothing on their own")
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
            brains=not args.no_brains,
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
