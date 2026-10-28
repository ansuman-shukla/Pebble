"""Writing and reading runs, events and snapshots in Postgres.

The engine is the only writer of runs, events and snapshots. Each tick is one transaction that ends with a
`NOTIFY pebble_events` carrying the run, tick and seq range, so live readers (M8) know what to fetch.
"""

import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from sqlalchemy import delete, insert, text
from sqlmodel import Session, col, select

from app.db.models import EngineCommand, Event, Run, Snapshot
from app.lib.ulid import UlidFactory
from app.observability.events import EventDraft
from app.sim.clock import game_minute
from app.sim.snapshot import SimSnapshot
from app.world.store import WorldKey

EVENTS_CHANNEL = "pebble_events"
COMMANDS_CHANNEL = "pebble_commands"


def _now() -> datetime:
    return datetime.now(UTC)


def create_run(session: Session, key: WorldKey, ids: UlidFactory, speed: int = 1, paused: bool = False) -> Run:
    run = Run(
        id=ids.new(),
        world_seed=key.seed,
        generator_version=key.generator_version,
        spec_hash=key.spec_hash,
        status="running",
        speed=speed,
        paused=paused,
    )
    session.add(run)
    session.flush()
    return run


def latest_run(session: Session, key: WorldKey | None = None) -> Run | None:
    statement = select(Run).order_by(col(Run.created_at).desc(), col(Run.id).desc())
    if key is not None:
        statement = statement.where(
            Run.world_seed == key.seed,
            Run.generator_version == key.generator_version,
            Run.spec_hash == key.spec_hash,
        )
    return session.exec(statement.limit(1)).first()


def latest_snapshot(session: Session, run_id: str, at_or_before: int | None = None) -> Snapshot | None:
    statement = select(Snapshot).where(Snapshot.run_id == run_id)
    if at_or_before is not None:
        statement = statement.where(Snapshot.tick <= at_or_before)
    return session.exec(statement.order_by(col(Snapshot.tick).desc()).limit(1)).first()


def events_after(session: Session, run_id: str, after_seq: int, until_tick: int | None = None) -> Sequence[Event]:
    statement = select(Event).where(Event.run_id == run_id, Event.seq > after_seq)
    if until_tick is not None:
        statement = statement.where(Event.tick <= until_tick)
    return session.exec(statement.order_by(col(Event.seq))).all()


def discard_after(session: Session, run_id: str, last_seq: int) -> int:
    """Drop events past a snapshot (the tail of a run that stopped without one); they are simulated again."""
    result = session.execute(delete(Event).where(col(Event.run_id) == run_id, col(Event.seq) > last_seq))
    return int(result.rowcount)  # type: ignore[attr-defined]  # DML results carry rowcount


def pending_commands(session: Session, run_id: str) -> Sequence[EngineCommand]:
    statement = select(EngineCommand).where(EngineCommand.run_id == run_id, col(EngineCommand.applied_at).is_(None))
    return session.exec(statement.order_by(col(EngineCommand.id))).all()


def queue_command(session: Session, run_id: str, kind: str, payload: dict[str, object]) -> EngineCommand:
    command = EngineCommand(run_id=run_id, kind=kind, payload=payload)
    session.add(command)
    session.flush()
    session.execute(text("SELECT pg_notify(:channel, :payload)"), {"channel": COMMANDS_CHANNEL, "payload": run_id})
    return command


class EventStore:
    """Writes one run's events and snapshots; resolves `cause_seq` to the cause's event id."""

    def __init__(self, session: Session, run: Run, ids: UlidFactory, clock: Callable[[], datetime] = _now) -> None:
        self.session = session
        self.run = run
        # kept apart: `run` expires on every commit and can't be refreshed once the connection is lost
        self.run_id = run.id
        self.ids = ids
        self.clock = clock
        self._ids_by_seq: dict[int, str] = {}

    def _cause_id(self, seq: int | None) -> str | None:
        if seq is None:
            return None
        if seq not in self._ids_by_seq:
            statement = select(Event.id).where(Event.run_id == self.run_id, Event.seq == seq)
            found = self.session.exec(statement).first()
            if found is None:
                raise ValueError(f"cause seq {seq} of run {self.run_id} is not stored")
            self._ids_by_seq[seq] = found
        return self._ids_by_seq[seq]

    def write(self, drafts: Sequence[EventDraft]) -> None:
        if not drafts:
            return
        now = self.clock()
        rows = []
        for draft in drafts:
            event_id = self.ids.new()
            rows.append(
                {
                    "id": event_id,
                    "run_id": self.run_id,
                    "seq": draft.seq,
                    "world_seed": self.run.world_seed,
                    "tick": draft.tick,
                    "game_time": game_minute(draft.tick),
                    "real_time": now,
                    "actor_kind": draft.actor_kind,
                    "actor_id": draft.actor_id,
                    "type": draft.type,
                    "cell": draft.cell,
                    "position": list(draft.position) if draft.position is not None else None,
                    "visibility": draft.visibility,
                    "cause_id": self._cause_id(draft.cause_seq),
                    "mind": None,
                    "payload": draft.payload.model_dump(mode="json"),
                }
            )
            self._ids_by_seq[draft.seq] = event_id
        self.session.execute(insert(Event), rows)
        self.notify(drafts[0].seq, drafts[-1].seq, drafts[-1].tick)

    def notify(self, first_seq: int, last_seq: int, tick: int) -> None:
        payload = json.dumps({"run_id": self.run_id, "tick": tick, "first_seq": first_seq, "last_seq": last_seq})
        self.session.execute(
            text("SELECT pg_notify(:channel, :payload)"), {"channel": EVENTS_CHANNEL, "payload": payload}
        )

    def snapshot(self, snapshot: SimSnapshot) -> Snapshot:
        row = Snapshot(
            id=self.ids.new(),
            run_id=self.run_id,
            tick=snapshot.tick,
            last_seq=snapshot.next_seq - 1,
            state=snapshot.model_dump(mode="json"),
        )
        self.session.add(row)
        return row

    def commit(self, tick: int, speed: int, paused: bool, status: str = "running") -> None:
        """Stamp the run's clock and heartbeat and commit everything written since the last commit."""
        self.run.tick, self.run.speed, self.run.paused, self.run.status = tick, speed, paused, status
        self.run.updated_at = self.clock()
        self.session.add(self.run)
        self.session.commit()
        if len(self._ids_by_seq) > 50_000:  # causes point back a little way; older ones are looked up
            self._ids_by_seq.clear()
