"""The engine process: the only writer of world state. `python -m app.engine` (or `make engine`).

Loads the stored world (current generator version) and the town, resumes the latest run of that world from its
latest snapshot (or starts a new run with the 22 citizens of `data/citizens/citizens.yaml`), then ticks:
1 tick = 1 game minute; `speed` = game seconds per real second (1 = real time, a tick every real minute; up to 600),
paused = no ticks.
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
from typing import get_args

import psycopg
from sqlalchemy import Engine as DbEngine
from sqlalchemy.exc import DBAPIError
from sqlmodel import Session

from app.brains.profile import BrainProfile, Ground, known_titles
from app.brains.routines import TRIP_LEGS
from app.brains.runner import CitizenBrains
from app.core.db import create_db_engine
from app.db.models import Run
from app.db.schemas import MAX_SPEED, ClockChange
from app.lib.ulid import UlidFactory
from app.observability.store import EventStore, create_run, discard_after, latest_run, latest_snapshot, pending_commands
from app.sim.citizens import CITIZENS, load_citizens
from app.sim.clock import SECONDS_PER_TICK, TICKS_PER_HOUR
from app.sim.destinations import COMPASS_BEARING, ROUGH_DISTANCE_M
from app.sim.navigation import Planner
from app.sim.ownership import fed_by_granary
from app.sim.simulation import Simulation
from app.sim.snapshot import SimSnapshot, restore, take_snapshot
from app.sim.snapshot import resumable as snapshot_resumable
from app.sim.vec import Vec3, step_towards
from app.sim.world import SimWorld, load_sim_world
from app.world.generate import GENERATOR
from app.world.spec import load_site_kinds, load_world_spec
from app.world.store import WorldKey, world_key
from app.world_api.facade import WorldApi
from app.world_api.models import Compass

POLL_S = 0.25  # how often a waiting engine looks for commands
HEARTBEAT_S = 1.0  # a waiting engine (paused, or between real-time ticks) stamps the run this often
RETRY_FIRST_S = 0.5  # reconnect backoff: doubles per failed attempt up to the cap, forever
RETRY_MAX_S = 10.0
APPLICATION_NAME = "pebble-engine"  # the engine's connections in pg_stat_activity
# SQLSTATE classes of a lost database: 08 connection exception, 57P operator intervention (shutdown, starting up)
LOST_DATABASE_STATES = ("08", "57P")
log = logging.getLogger("pebble.engine")

Brain = Callable[[Simulation], None]  # called before every tick
HOME_AREAS = {"town": "town", "band_a": "band_a_camp", "band_b": "band_b_camp"}  # region -> its home place id
GROUNDS_M = (450.0, 1000.0)  # a band's food grounds: past the thin home ring, the middle ring (10 §1.2)
GROUND_FOOD = frozenset({"berries", "roots", "nuts"})
GROUNDS_KEPT = 3
GROUND_LEAST = 100  # food (pieces when full) a way must hold to be worth the walk
DEN_CLEAR_M = 150.0  # forage trips keep this far from the dens (a bold hunter walked into a wolf's den on one)
GATHER_SPREAD_M = 150.0  # how far from where a walk ends foragers go for the food they see ("some way off")
STOP_CLEAR_M = DEN_CLEAR_M + GATHER_SPREAD_M  # so a trip's stops keep this far from the dens


def forage_grounds(world: SimWorld, region: str) -> tuple[Ground, ...]:
    """The ways from a band's camp its food lies beyond the home ring (10 §1.2), most first: the land a band knows,
    given to its scripted brains (a mind learns it by walking it). The band knows its dens too: food by a den doesn't
    count, and a trip's stops (the long walk out, then each short walk on) keep STOP_CLEAR_M from every den (the food a
    forager walks to from there then lies DEN_CLEAR_M clear), so a way whose first stop is too near one isn't taken
    and the walks on stop short of one."""
    if region == "town":
        return ()
    camp = world.places[HOME_AREAS[region]].centre
    dens = [feature.position for feature in world.features if feature.kind == "den"]
    totals = world.nodes.food_by_bearing(world.grid, camp, *GROUNDS_M, GROUND_FOOD, avoid=dens, clear_m=DEN_CLEAR_M)
    ways: tuple[Compass, ...] = get_args(Compass)  # north first, clockwise: the sectors' order
    ranked = sorted(range(len(totals)), key=lambda sector: (-totals[sector], sector))
    grounds: list[Ground] = []
    for sector in ranked:
        if totals[sector] < GROUND_LEAST or len(grounds) == GROUNDS_KEPT:
            break
        legs = _clear_legs(world, camp, ways[sector], dens)
        if legs >= 0:
            grounds.append(Ground(ways[sector], legs))
    return tuple(grounds)


def _clear_legs(world: SimWorld, camp: Vec3, way: Compass, dens: Sequence[Vec3]) -> int:
    """How many short walks on past the long walk out keep every stop STOP_CLEAR_M from the dens (-1: not even the
    long walk's end)."""
    for leg in range(TRIP_LEGS + 1):
        metres = ROUGH_DISTANCE_M["a long walk"] + leg * ROUGH_DISTANCE_M["a short walk"]
        stop = step_towards(camp, COMPASS_BEARING[way], metres, world.radius_m)
        if any(world.distance_m(stop, den) < STOP_CLEAR_M for den in dens):
            return leg - 1
    return TRIP_LEGS


def citizen_brains(sim: Simulation, seed: int) -> CitizenBrains:
    """A scripted brain for every citizen, acting through their own `WorldApi`."""
    places = sim.world.places
    cast = sim.state.citizens
    traits = {spec.id: spec.traits for spec in load_citizens(CITIZENS).citizens if spec.traits is not None}
    grounds = {region: forage_grounds(sim.world, region) for region in HOME_AREAS}
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
                    skills=citizen.skills,
                    titled=known_titles(
                        (cast[other].name, cast[other].role) for other in sorted(citizen.people) if other in cast
                    ),
                    granary=citizen.region == "town" and fed_by_granary(citizen),
                    honesty=traits[citizen.id].honesty if citizen.id in traits else 0.5,
                    grounds=grounds[citizen.region],
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
    speed: int = 1  # game seconds per real second (1 = real time); a tick (1 game minute) every 60 / speed real s
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
    now: Callable[[], float] = time.monotonic
    game_seconds: float = 0.0  # real-time game seconds passed since the last tick (a tick is due at SECONDS_PER_TICK)
    counted_at: float | None = None  # when game_seconds was last brought up to date
    beat_at: float | None = None  # when a waiting engine last stamped its heartbeat

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

    def run_ticks(self, ticks: int | None, headless: bool) -> None:
        """Tick until `ticks` more ticks have run (None = forever) or a stop signal; headless never sleeps.

        A lost database connection reloads the last committed state and carries on toward the same final tick.
        """
        until = None if ticks is None else self.sim.tick + ticks
        self.counted_at = self.now()
        while not self.stopping and (until is None or self.sim.tick < until):
            try:
                self._advance(headless)
            except DBAPIError as error:
                if not is_connection_loss(error):
                    raise
                self.recover(error)
                self.counted_at = self.now()  # the outage isn't game time: carry on from where the clock stood

    def _advance(self, headless: bool) -> None:
        """One pass of the loop: count the game time passed, apply commands, then tick, wait or heartbeat.

        Game time runs at `speed` game seconds per real second while unpaused; a tick is due every SECONDS_PER_TICK
        of it. A speed change mid-wait keeps the game seconds already passed, so the next tick comes as soon as the
        new speed completes the minute (clients drawing the walk between ticks stay in step).
        No transaction stays open while the loop waits: the connection goes back to the pool, which pre-pings it
        before the next poll (a waiting engine used to sit `idle in transaction` on the poll's read).
        """
        realtime = not headless and self.sim.tick >= self.catch_up_to
        self._count_game_time(realtime)
        self.apply_commands()
        if realtime:
            wait = POLL_S if self.clock.paused else (SECONDS_PER_TICK - self.game_seconds) / self.clock.speed
            if wait > 0:
                self._heartbeat()
                self.idle_sleep(min(wait, POLL_S))
                return
            self.game_seconds -= SECONDS_PER_TICK
        started = time.perf_counter()
        self.tick()
        if self.sim.tick % TICKS_PER_HOUR == 0:
            log.info("tick %s (%.1f ms)", self.sim.tick, (time.perf_counter() - started) * 1000)

    def _heartbeat(self) -> None:
        """Stamp the run about once a second while no ticks come (a tick a real minute at ×1), so spectators see the
        engine is alive; in between, just end the poll's read."""
        now = self.now()
        if self.beat_at is None or now - self.beat_at >= HEARTBEAT_S:
            self.store.commit(self.sim.tick, self.clock.speed, self.clock.paused)
            self.beat_at = now
        else:
            self.store.session.commit()

    def _count_game_time(self, realtime: bool) -> None:
        """Add the game seconds passed at the current speed since the last count (none while paused or catching up)."""
        now = self.now()
        if realtime and not self.clock.paused and self.counted_at is not None:
            self.game_seconds += (now - self.counted_at) * self.clock.speed
        self.counted_at = now

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
        # a reload while catching up resumes from a run committed short of the old target: keep that target
        self.catch_up_to = max(self.catch_up_to, fresh.catch_up_to)

    def shut_down(self) -> None:
        """Snapshot where we are so a restart loses nothing (unless that snapshot is stored already: the hour's, or
        the one a run resumed from and stopped again before ticking), and mark the run stopped."""
        stored = latest_snapshot(self.store.session, self.store.run_id)
        if stored is None or stored.last_seq != self.sim.state.next_seq - 1:
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
        sim.add_cast(load_citizens(citizens))
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
    """Continue a run from its latest snapshot; events after it (an unclean stop) are dropped and re-simulated,
    up to the tick the run had committed without real-time waits (spectators already saw those ticks)."""
    snapshot_row = latest_snapshot(session, run.id)
    if snapshot_row is None:
        raise ValueError(f"run {run.id} has no snapshot to resume from")
    snapshot = SimSnapshot.model_validate(snapshot_row.state)
    committed_tick = run.tick
    dropped = discard_after(session, run.id, snapshot_row.last_seq)
    clock.speed, clock.paused = run.speed, run.paused
    sim = Simulation(world, restore(snapshot), planner)
    store = EventStore(session, run, ids)
    store.commit(sim.tick, clock.speed, clock.paused)
    log.info("resumed run %s at tick %s (dropped %s events past the snapshot)", run.id, sim.tick, dropped)
    hooks: list[Brain] = [citizen_brains(sim, run.world_seed)] if brains else []
    return EngineLoop(sim=sim, store=store, clock=clock, brains=hooks, catch_up_to=committed_tick)


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
    """Whether this simulation can continue the run (its latest snapshot has the current snapshot and system
    versions)."""
    snapshot_row = latest_snapshot(session, run.id)
    return snapshot_row is not None and snapshot_resumable(snapshot_row.state)


def main(argv: Sequence[str] | None = None, db_engine: DbEngine | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.engine", description=__doc__.splitlines()[0])
    parser.add_argument("--new-run", action="store_true", help="start a new run instead of resuming the latest")
    parser.add_argument(
        "--speed",
        type=int,
        default=None,
        help=f"game seconds per real second, 1 (real time, the default for a new run)..{MAX_SPEED}",
    )
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
